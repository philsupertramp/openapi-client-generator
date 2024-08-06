from openapi_client_generator.string_utils import slugify, drop_quotes


def handle_any_all_of(property):
    for key in ['anyOf', 'allOf']:
        if key in property:
            types = [get_type(sub_prop) for sub_prop in property.get(key, [])]
            if 'null' in types:
                types.remove('null')
                return f"Optional[{types[0]}]"
            types = list(set(types))
            if len(types) == 1:
                return types[0]
            return 'Union[' + ', '.join(types) + ']'
    return None


def get_type(property):
    if property is None:
        return 'None'

    type_mapping = {
        'integer': 'int',
        'string': 'str',
        'boolean': 'bool',
        'object': 'dict',
        'enum': property.get('title', 'Any'),
        'array': f"List[{get_type(property.get('items', None))}]"
    }

    any_all_of_result = handle_any_all_of(property)
    if any_all_of_result is not None:
        return any_all_of_result

    prop_type = property.get('type')

    if prop_type == 'string' and property.get('enum') is not None:
        return 'Literal[' + ', '.join([f"'{value}'" for value in property.get('enum', [])]) + ']'
    if prop_type == 'string' and property.get('format') == 'uuid':
        return 'UUID'

    if '$ref' in property:
        reference = property.get('$ref')[1:].split('/')[-1]
        return f"'{reference}'"

    if 'type' not in property and 'title' in property:
        return f"'{property.get('title')}'"

    return type_mapping.get(prop_type, 'Any')


def parse_properties(properties, required):
    parsed_properties = {}
    base_class = properties.pop('base_class', 'BaseModel')
    if base_class == 'Enum':
        enums = properties.pop('enums')
        enum_type = properties.pop('enum_type', 'str')
        base_class = f'{enum_type}, Enum'
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


def parse_enum_schema(schema):
    type_ = schema.get('type', 'str')
    type_ = 'str' if type_ == 'string' else type_
    properties = {'enums': schema['enum'], 'base_class': 'Enum', 'enum_type': type_}
    enum_objects = {schema.get('title', 'MyModel'): [e.upper() if type_ == 'str' else e for e in schema['enum']]}
    return properties, enum_objects

def parse_ref_schema(prop, enum_objects):
    for sub_prop in prop['allOf']:
        reference = sub_prop.get('$ref', "")[1:].split('/')[-1]
        if reference in enum_objects:
            return {
                'type': 'enum',
                'title': reference,
                'default': f'{reference}.{prop.get("default", "").upper()}'
            }
    return prop

def parse_properties_schema(properties, enum_objects):
    return {name: parse_ref_schema(prop, enum_objects) if 'allOf' in prop else prop for name, prop in properties.items()}

def get_content_schema(content):
    return content.get('schema', {})

def get_ref_schema(schema):
    reference = schema['$ref'][1:].split('/')[-1]
    return {'type': f'models.{reference}', 'title': slugify(reference)}

def get_anyOf_schema(schema):
    types = [get_type(sub_prop) for sub_prop in schema['anyOf']]
    if 'null' in types:
        types.remove('null')
        return {'type': f"Optional[{types[0]}]", 'title': slugify(types[0])}
    types = sorted(list(set(types)))
    if len(types) > 1:
        return get_union_schema(types)
    if isinstance(types[0], list):
        return get_first_non_container_type(types)
    return {'type': types[0], 'title': slugify(types[0])}

def get_union_schema(types):
    types = sorted(list(set(types)))
    return {'type': 'Union[' + ', '.join(types) + ']', 'title': slugify(drop_quotes(types[0]))}

def get_first_non_container_type(types):
    idx = 0
    type_ = None
    while type_ is None and idx < len(types):
        type_ = types[idx]
        type_ = None if isinstance(type_, [list, tuple, dict, set]) else type_
        idx += 1
    type_ = (type_ or 'Any').replace("'", "")
    return {'type': type_, 'title': slugify(type_)}


def process_request_body(request_body, is_required=False):
    request_body_params = []
    for content_type, content in request_body.items():
        if content_type != 'application/json':
            continue
        schema = get_content_schema(content)
        elem = {'required': is_required}
        if '$ref' in schema:
            request_body_params.append({**elem, **get_ref_schema(schema)})
        elif 'items' in schema:
            if 'anyOf' in schema['items']:
                ref_schema = get_anyOf_schema(schema['items'])
            else:
                ref_schema = get_ref_schema(schema['items'])
            ref_schema['type'] = f'list[{ref_schema["type"]}]'
            request_body_params.append({**elem, **ref_schema})
        elif 'anyOf' in schema:
            request_body_params.append({**elem, **get_anyOf_schema(schema)})
    return request_body_params
