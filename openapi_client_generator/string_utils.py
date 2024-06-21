def slugify(text):
    replacement_map = {
        '-': '_',
        ' ': '_',
        '.': '_',
        '/': '_',
        '\\': '_',
        '(': '',
        ')': '',
        '?': '',
    }
    for key, value in replacement_map.items():
        text = text.replace(key, value)
    # transform camelCase to snake_case find uppercase letters and add underscore before them
    text = ''.join(['_' + char.lower() if char.isupper() else char for char in text.strip()]).lstrip('_').rstrip('_')

    # remove leading underscores
    while text.startswith('_'):
        text = text[1:]
    return text

def drop_quotes(text):
    return text.replace("'", "").replace('"', '')

