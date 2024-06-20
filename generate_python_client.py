import json
import os
import re
import argparse
from jinja2 import Environment, FileSystemLoader
from openapi_spec_validator import validate_spec


model_registry = {}
enum_objects = {}


def slugify(text):
    # transform camelCase to snake_case
    # find uppercase letters and add underscore before them
    text = ''.join(['_' + char.lower() if char.isupper() else char for char in text]).lstrip('_')
    return text.replace('-', '_').replace(' ', '_').replace('.', '_').replace('/', '_').replace('\\', '_')


def get_type(property):
    if 'anyOf' in property:
        types = [get_type(sub_prop) for sub_prop in property['anyOf']]
        if 'null' in types:
            types.remove('null')
            return f"Optional[{types[0]}]"
        types = list(set(types))
        if len(types) == 1:
            return types[0]
        return 'Union[' + ', '.join(types) + ']'
    if 'allOf' in property:
        types = [get_type(sub_prop) for sub_prop in property['allOf']]
        if 'null' in types:
            types.remove('null')
            return f"Optional[{types[0]}]"
        types = list(set(types))
        if len(types) == 1:
            return types[0]
        return 'Union[' + ', '.join(types) + ']'
    if property.get('type') == 'integer':
        return 'int'
    if property.get('type') == 'string':
        if property.get('enum') is not None:
            return 'Literal[' + ', '.join([f"'{value}'" for value in property['enum']]) + ']'
        if property.get('format') == 'uuid':
            return 'UUID'
        return 'str'
    if property.get('type') == 'boolean':
        return 'bool'
    if property.get('type') == 'object':
        return 'dict'
    if property.get('type') == 'enum':
        return property.get('title', 'Any')
    if property.get('type') == 'array':
        return f"List[{get_type(property['items'])}]"
    if '$ref' in property:
        reference = property['$ref'][1:]
        reference = reference.split('/')[-1]
        return f"'{reference}'"
    if 'type' not in property and 'title' in property:
        return f"'{property['title']}'"
    return 'Any'

def parse_properties(properties, required):
    parsed_properties = {}
    base_class = properties.pop('base_class', 'BaseModel')
    if base_class == 'Enum':
        enums = properties.pop('enums')
        enum_type = properties.pop('enum_type', 'str')
        parsed_properties = {enum.upper(): {'title': enum, 'default': f"'{enum}'", 'type': enum_type} for enum in enums}
        return parsed_properties, base_class

    for name, prop in properties.items():
        type_ = get_type(prop)
        default = prop.get('default', None)
        if type_ == 'str' and prop.get('format') == 'date-time':
            type_ = 'datetime'
        if type_ == 'str':
            default = f"'{default}'"
        parsed_properties[name] = {
            'type': type_,
            'title': prop.get('title', ''),
            'default': default,
            'required': name in required,
        }
    return parsed_properties, base_class

def generate_pydantic_model(schema, template_path):
    model_name = schema.get('title', 'MyModel')
    properties = schema.get('properties', {})
    required = schema.get('required', [])
    if not properties:
        if 'enum' in schema:
            type_ = schema.get('type', 'str')
            if type_ == 'string':
                type_ = 'str'
            properties = {'enums': schema['enum'], 'base_class': 'Enum', 'enum_type': type_}
            enum_objects[model_name] = [e.upper() if type_ == 'str' else e for e in schema['enum']]
    else:
        # find all enum fields
        new_properties = {}
        for name, prop in properties.items():
            if 'allOf' in prop:
                for sub_prop in prop['allOf']:
                    if '$ref' in sub_prop:
                        reference = sub_prop['$ref'][1:]
                        reference = reference.split('/')[-1]
                        if reference in enum_objects:
                            prop = {
                                'type': 'enum', 
                                'title': reference,#prop.get('title', ''), 
                                'default': f'{reference}.{prop.get("default", "").upper()}'
                            }
            new_properties[name] = prop
        properties = new_properties
    parsed_properties, base_class = parse_properties(properties, required)

    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template(template_path)
    model_code = template.render(model_name=model_name, properties=parsed_properties, base_class=base_class)
    return model_code


def generate_client(openapi_json_path, output_dir, token_type='Basic'):
    with open(openapi_json_path, 'r') as file:
        spec = json.load(file)

    # Validate the OpenAPI spec
    try:
        validate_spec(spec)
    except Exception as e:
        tb = e.__traceback__
        print(f'\033[91mError validating OpenAPI spec:\n{str(tb)}\033[0m') # ]] to silence IDE warnings


    # create directory if it doesn't exist
    output_dir = os.path.join(output_dir, output_dir.split('/')[-1])
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
        model_code = generate_pydantic_model(schema, './templates/model_template.j2')
        models[name] = model_code
    for name, schema in filter(lambda x: 'enum' not in x[1], schemas.items()):
        model_code = generate_pydantic_model(schema, './templates/model_template.j2')
        models[name] = model_code

    # Write the model definitions into the template file
    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template('./templates/model_module_template.j2')
    model_module_code = template.render(models=models.values())
    # Write the rendered code to a file
    if models:
        with open(os.path.join(output_dir, 'models.py'), 'w') as file:
            file.write(model_module_code)

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
                'params': param_names + query_params,
                'query_params': ', '.join(f"'{param}': {param}" for param in query_params),
                'description': operation.get('summary', ''),
            }
            request_body_params = []
            requires_body = http_method in ['post', 'put', 'patch']
            if requires_body:
                # Add a breakpoint()
                request_body = operation.get('requestBody', {}).get('content', {})
                if request_body:
                    for content_type, content in request_body.items():
                        if content_type == 'application/json':
                            schema = content['schema']
                            if '$ref' in schema:
                                # Add a breakpoint()
                                reference = content['schema']['$ref'][1:]
                                reference = reference.split('/')[-1]
                                request_body_params.append({'type': f'models.{reference}', 'title': slugify(reference)})
                            elif 'anyOf' in schema:
                                types = [get_type(sub_prop) for sub_prop in schema['anyOf']]
                                if 'null' in types:
                                    types.remove('null')
                                    request_body_params.append({'type': f"Optional[{types[0]}]", 'title': slugify(types[0])})
                                types = sorted(list(set(types)))
                                if len(types) == 1:
                                    request_body_params.append({'type': types[0], 'title': slugify(types[0])})
                                else:
                                    type_ = types[0]
                                    if isinstance(type_, list):
                                        idx = 0
                                        type_ = None if isinstance(type_, [list, tuple, dict, set]) else type_
                                        while type_ == None and idx < len(types):
                                            type_ = type_[idx]
                                            type_ = None if isinstance(type_, [list, tuple, dict, set]) else type_
                                            idx += 1
                                    type_ = (type_ or 'Any').replace("'", "")
                                    types = list(set(types))
                                    request_body_params.append({'type': 'Union[' + ', '.join(types) + ']', 'title': slugify(type_)})


                    definition['request_body'] = request_body_params

            responses = operation.get('responses', {})
            return_types = []
            return_ctors = []
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
                if is_success and return_types:
                    last_return = return_types[-1]
                    if 'List' in last_return:
                        return_ctor = re.findall(r'\[(.*?)\]', last_return)[0]
                    else:
                        return_ctor = last_return
                    return_ctors.append(return_ctor)

            return_ctors = list(set(return_ctors))
            return_types = list(set(return_types))

            if len(return_types) == 1:
                definition['return_type'] = return_types[0]
                definition['return_ctor'] = return_ctors[0]

            elif len(return_types) > 1:
                return_types = list(set(return_types))
                definition['return_type'] = 'Union[' + ', '.join(return_types) + ']'
                if len(return_ctors) == 1:
                    definition['return_ctor'] = return_ctors[0]
                else:
                    new_return_ctors = [c for c in return_ctors if c not in ['dict', 'list', 'Any']]
                    if len(new_return_ctors) < 1:
                        definition['return_ctor'] = return_ctors[0]
                    else:
                        definition['return_ctor'] = new_return_ctors[0]
            
            if 'return_ctor' in definition and  'List' in definition['return_ctor']:
                definition['return_ctor'] = re.findall(r'\[(.*?)\]', definition['return_ctor'])[0]
            else:
                definition['return_ctor'] = 'dict'
            methods.append(definition)

    # Load and render the template
    template_path = './templates/client_template.j2'
    output_file = 'client.py'
    app_name = spec.get('info', {}).get('title', 'OpenAPI Client').title().replace('Api', 'API').replace(' ', '')
    client_module_name = '/'.join(output_dir.split('/')[:-1])
    if client_module_name.startswith('./'):
        client_module_name = client_module_name[2:]
    if client_module_name.endswith('/'):
        client_module_name = client_module_name[:-1]

    client_module_name = client_module_name.replace('/', '.')

    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template('./templates/README_template.j2')
    readme_content = template.render(
        project_name=app_name,
        client_module_name=f'{client_module_name}.client',
        model_module_name=f'{client_module_name}.models',
        methods=methods,
    )

    with open(os.path.join(output_dir, '../README.md'), 'w') as file:
        file.write(readme_content)

    template = env.get_template('./templates/requirements_template.j2')
    requirements_content = template.render()
    with open(os.path.join(output_dir, '../requirements.txt'), 'w') as file:
        file.write(requirements_content)


    template = env.get_template(template_path)
    client_code = template.render(
        app_name=app_name,
        methods=methods,
        client_module_name=client_module_name.replace('/', '.'),
        token_type=token_type,
    )

    # Write the rendered code to a file
    with open(os.path.join(output_dir, output_file), 'w') as file:
        file.write(client_code)

    if not models:
        print('\033[91mNo models found in the OpenAPI spec!\033[0m')  # ]] to silence IDE warnings

    return output_dir



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate a Python client from an OpenAPI spec')
    parser.add_argument('openapi_json_file', type=str, help='Path to the OpenAPI JSON file')
    parser.add_argument('output_dir', type=str, help='Path to the output directory')
    parser.add_argument('--token-type', type=str, default='Basic', help='Type of token to use for authentication')

    args = parser.parse_args()

    client_file = generate_client(
        args.openapi_json_file,
        args.output_dir,
        args.token_type,
    )
    print(f'\033[92mGenerated Python client: {client_file}\033[0m') # ]] to silence IDE warnings
