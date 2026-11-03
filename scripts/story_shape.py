"""Collect actionable JSON field/type errors before rendering or semantic validation."""


def shape_errors(story):
    errors = []
    if not isinstance(story, dict):
        return ['$: story需为对象']

    def expect(value, cls, path, hint):
        if not isinstance(value, cls):
            errors.append(path + ': ' + hint + '; got ' + type(value).__name__)
            return False
        return True

    object_fields = {'overview', 'portrait', 'scene', 'letter', 'song', 'share', 'bgm', 'target'}
    object_lists = {'themes', 'findings', 'milestones', 'wishes', 'plans', 'annual_reviews',
                    'evidence', 'objects', 'hotspots', 'entries'}
    string_lists = {'paragraphs', 'source_ids', 'image_source_ids', 'image_paths'}
    strings = {'source_id', 'title', 'headline', 'text', 'reason', 'opening', 'closing',
               'description', 'letter_text', 'excerpt', 'quote', 'observation', 'image_path',
               'image_alt', 'alt', 'caption', 'name', 'label', 'object_name', 'placement'}

    def walk(value, path='$'):
        if not isinstance(value, dict): return
        for key, child in value.items():
            here = path + '.' + key
            if key == 'supports':
                continue  # Legacy metadata is ignored by the simplified contract.
            if key == 'evidence' and '.objects[' in path:
                expect(child, str, here, '物件依据需为原文字符串')
            elif key in object_fields:
                if child is None and key in {'bgm', 'song', 'scene', 'letter'}: continue
                if expect(child, dict, here, '需为对象'): walk(child, here)
            elif key == 'image_captions':
                if expect(child, dict, here, '需为 {图片路径: 说明文字} 对象'):
                    for image, caption in child.items():
                        expect(caption, str, here + '[' + repr(image) + ']', '说明需为字符串')
            elif key in object_lists:
                if expect(child, list, here, '需为对象数组'):
                    for n, item in enumerate(child):
                        item_path = f'{here}[{n}]'
                        if expect(item, dict, item_path, '需为对象'):
                            if key == 'hotspots' and 'source_ids' not in item:
                                errors.append(item_path + '.source_ids: 缺少关联来源ID数组')
                            if key == 'entries' and path == '$.share' and 'source_id' not in item:
                                errors.append(item_path + '.source_id: 缺少单个来源ID字符串')
                            walk(item, item_path)
            elif key in string_lists:
                if expect(child, list, here, '需为字符串数组'):
                    for n, item in enumerate(child): expect(item, str, f'{here}[{n}]', '需为字符串')
            elif key in strings:
                expect(child, str, here, '需为字符串')
    walk(story)
    return errors
