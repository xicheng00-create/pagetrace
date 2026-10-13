"""UP-013：出卡/去重的固定前缀集中管理；动态书文只置于末尾 user 消息。

仅提供适配接口，不代替尚未实现的契约切分与出卡闸门。
"""
PREFIXES = {
    'cardgen': ('仅依据提供的书籍文本生成考点，不得引入外部事实。只输出 JSON 数组。'
                '每项包含 contract=1、concept_id（稳定字符串）、subject、book、chapter、title、'
                'question、answer_points（原文要点数组）、confidence（high/medium/low）。'
                '要点正文总字数超过222时，另给 subcards 数组，按原文标点分片连续贪心装箱，'
                '每箱最多222字；每项含 name（子卡短名）和 question（该子卡独立问句）。'
                '不得重写要点，不得补字；无法满足时不要输出该考点。'),
    'dedupe': '仅比较提供的知识卡片，识别重复内容；不得引入外部事实。只输出 JSON。',
}


def messages_for(feature, text):
    return [{'role': 'system', 'content': PREFIXES[feature]},
            {'role': 'user', 'content': text}]
