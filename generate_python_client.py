import json
import os
import re
import argparse
from jinja2 import Environment, FileSystemLoader
from openapi_spec_validator import validate_spec
from openapi_client_generator.string_utils import slugify, drop_quotes
from openapi_client_generator.schema_utils import parse_properties, parse_enum_schema, parse_properties_schema, process_request_body


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

model_registry = {}
enum_objects = {}

__version__ = '0.0.2'


def generate_pydantic_model(schema, template_path):
    global enum_objects
    model_name = schema.get('title', 'MyModel')
    properties = schema.get('properties', {})
    required = schema.get('required', [])
    
    if not properties and 'enum' in schema:
        properties, enum_object = parse_enum_schema(schema)
        key = list(enum_object.keys())[0]
        enum_objects[key] = enum_object[key]
    else:
        properties = parse_properties_schema(properties, enum_objects)
    
    parsed_properties, base_class = parse_properties(properties, required)

    env = Environment(loader=FileSystemLoader(CURRENT_DIR))
    template = env.get_template(template_path)
    model_code = template.render(model_name=model_name, properties=parsed_properties, base_class=base_class)
    
    return model_code


def render_template(template_name, output_file, **kwargs):
    env = Environment(loader=FileSystemLoader(CURRENT_DIR))
    template = env.get_template(template_name)
    with open(output_file, 'w') as file:
        file.write(template.render(**kwargs))


def process_responses(responses):
    return_types = []
    return_ctors = {}
    for status_code, response in responses.items():
        is_success = status_code.startswith('2')
        if 'content' in response:
            ref = response['content']['application/json']['schema']
            if ref.get('type') == 'array':
                refs = ref['items']
                if '$ref' not in refs:
                    return_types.append('List[dict]')
                else:
                    reference = refs['$ref'][1:].split('/')[-1]
                    return_types.append(f'List[models.{reference}]')
            else:
                if '$ref' not in ref:
                    return_types.append('dict')
                else:
                    reference = ref['$ref'][1:].split('/')[-1]
                    return_types.append(f'models.{reference}')
        if return_types:
            last_return = return_types[-1]
            if '[' in last_return or ']' in last_return:
                return_ctor = re.findall(r'\[(.*?)\]', last_return)[0]
            else:
                return_ctor = last_return
            if status_code not in return_ctors:
                return_ctors[status_code] = [return_ctor]
            else:
                return_ctors[status_code].append(return_ctor)

    return list(set(return_types)), return_ctors


def parse_methods(spec):
    methods = []
    for path, path_item in spec.get('paths', {}).items():
        for http_method, operation in path_item.items():
            if http_method not in ['get', 'post', 'put', 'delete', 'patch']:
                continue

            method_name = operation.get('operationId') or f"{http_method}_{path.replace('/', '_').replace('{', '').replace('}', '')}"
            params = operation.get('parameters', [])
            param_names = [param['name'] for param in params if param['in'] == 'path']
            query_params = [param['name'] for param in params if param['in'] == 'query']
            endpoint = path
            for param in param_names:
                endpoint = endpoint.replace(param, f"{param}")

            definition = {
                'name': method_name,
                'http_method': http_method.upper(),
                'endpoint': endpoint,
                'params': param_names,
                'query_params': query_params,
                'description': operation.get('summary', ''),
            }
            request_body_params = []
            requires_body = http_method in ['post', 'put', 'patch']
            if requires_body:
                request_body = operation.get('requestBody', {}).get('content', {})
                if request_body:
                    request_body_params = process_request_body(request_body)
                    definition['request_body'] = request_body_params

            # figure out return type and constructor
            responses = operation.get('responses', {})
            return_types, return_ctors = process_responses(responses)

            if len(return_types) == 1:
                definition['return_type'] = return_types[0]
                definition['return_ctor'] = return_ctors

            elif len(return_types) > 1:
                return_types = list(set(return_types))
                definition['return_type'] = 'Union[' + ', '.join(return_types) + ']'
                definition['return_ctor'] = return_ctors
            else:
                # something went wrong
                definition['return_type'] = 'None'
            
            if 'return_ctor' not in definition:
                definition['return_ctor'] = 'dict'

            if 'return_ctor' in definition:
                definition['return_ctor'] = '{\n' + ' ' * 16 + (',\n' + ' ' * 16).join([f'{status_code}: {response[0]}' for status_code, response in definition['return_ctor'].items()]) + '\n' + ' ' * 12 + '}'
            methods.append(definition)
    return methods


def generate_client(openapi_json_path, og_output_dir, client_module_name, project_name, token_type='Basic', async_=False, username=None, version=None):
    with open(openapi_json_path, 'r') as file:
        spec = json.load(file)

    openapi_version = spec.get('openapi')
    swagger_version = spec.get('swagger')

    if not openapi_version and not swagger_version:
        print('\033[91mInvalid OpenAPI spec: unsupported spec!\033[0m') # ]] to silence IDE warnings
        raise ValueError('Invalid OpenAPI spec: unsupported spec!')

    # Validate the OpenAPI spec
    try:
        validate_spec(spec)
    except Exception as e:
        tb = e.__traceback__
        print(f'\033[91mError validating OpenAPI spec:\n{str(tb)}\033[0m') # ]] to silence IDE warnings

    # create directory if it doesn't exist
    client_module_name = slugify(client_module_name)
    output_dir = os.path.join(og_output_dir, client_module_name)
    os.makedirs(output_dir, exist_ok=True)

    # create __init__.py file if it doesn't exist
    with open(os.path.join(output_dir, '__init__.py'), 'w') as file:
        pass

    # create models directory if it doesn't exist
    # Generate Pydantic models
    models = {}
    # first build enums, then build models
    schemas = spec.get('components', {}).get('schemas', {})
    for name, schema in filter(lambda x: 'enum' in x[1], schemas.items()):
        model_code = generate_pydantic_model(schema, 'templates/model_template.j2')
        models[name] = model_code
    for name, schema in filter(lambda x: 'enum' not in x[1], schemas.items()):
        model_code = generate_pydantic_model(schema, 'templates/model_template.j2')
        models[name] = model_code

    methods = parse_methods(spec)

    # Load and render the template
    app_name = spec.get('info', {}).get('title', 'OpenAPI Client').title().replace('Api', 'API').replace(' ', '')
    if client_module_name.startswith('./'):
        client_module_name = client_module_name[2:]
    if client_module_name.endswith('/'):
        client_module_name = client_module_name[:-1]

    client_module_name = client_module_name.replace('/', '.')

    if not models:
        print('\033[91mNo models found in the OpenAPI spec!\033[0m') # ]] to silence IDE warnings
    if not methods:
        print('\033[91mNo methods found in the OpenAPI spec!\033[0m') # ]] to silence IDE warnings
    
    client_args = {
        'app_name': app_name,
        'methods': methods,
        'client_module_name': client_module_name.replace('/', '.'),
        'token_type': token_type,
    }
    
    render_template('templates/model_module_template.j2', os.path.join(output_dir, 'models.py'), models=models.values())
    render_template('templates/client_template.j2', os.path.join(output_dir, 'client.py'), **client_args)
    if async_: render_template('templates/async_client_template.j2', os.path.join(output_dir, 'async_client.py'), **client_args)
    render_template(
        'templates/README_template.j2', os.path.join(output_dir, '../README.md'), 
        app_name=app_name, project_name=project_name, client_module_name=f'{client_module_name}.client', 
        model_module_name=f'{client_module_name}.models', methods=methods
    )
    render_template(
        'templates/pyproject_template.j2', os.path.join(output_dir, '../pyproject.toml'),
        project_name=project_name, client_module_name=client_module_name, version=version, username=username
    )

    return output_dir



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate a Python client from an OpenAPI spec')
    parser.add_argument('command', type=str, help='Command to run')
    parser.add_argument('openapi_json_file', type=str, help='Path to the OpenAPI JSON file')
    parser.add_argument('output_dir', type=str, help='Path to the output directory')
    parser.add_argument('--client-module-name', type=str, default='client', help='Name of the client module')
    parser.add_argument('--token-type', type=str, default='Basic', help='Type of token to use for authentication')
    parser.add_argument('--async', dest='async_', action='store_true', help='Generate an async client (default: False)')

    parser.add_argument('--upload', action='store_true', help='Upload the generated client to PyPI (default: False)')
    parser.add_argument('--username', type=str, help='PyPI username')
    parser.add_argument('--version', type=str, help='Version of the package to upload')
    parser.add_argument('--project_name', type=str, default='client_library', help='Name of the project')

    args = parser.parse_args()

    if args.command == 'help':
        parser.print_help()
        exit()

    if args.command == 'version':
        print(__version__)
        exit()

    if args.command not in ['generate']:
        print('\033[91mInvalid command!\033[0m') # ]] to silence IDE warnings

    if args.command == 'generate':
        client_file = generate_client(
            args.openapi_json_file,
            args.output_dir,
            args.client_module_name,
            args.project_name,
            args.token_type,
            args.async_,
            args.username,
            args.version,
        )
        print(f'\033[92mGenerated Python client: {client_file}\033[0m') # ]] to silence IDE warnings

    if args.upload:
        if not args.username or not args.version:
            print('\033[91mPlease provide a username and version to upload the package!\033[0m') # ]] to silence IDE warnings
            exit()
        print('\033[92mUploading package to PyPI...\033[0m') # ]] to silence IDE warnings
