from __future__ import annotations


DISH_WORDS = {
    "бургер",
    "донер",
    "картофель",
    "кебаб",
    "курица",
    "меню",
    "пицца",
    "ролл",
    "салат",
    "свинины",
    "суп",
    "шаурма",
    "шашлык",
}


def classify_entity_type(title: str, context: str) -> str:
    haystack = f"{title} {context}".lower()
    if any(word in haystack for word in DISH_WORDS):
        return "dish"
    return "generic"
