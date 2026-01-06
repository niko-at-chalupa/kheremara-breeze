import re

def _normalize_token(token: str) -> str:
    # Case 1: spaced-out letters (f>u>c>k, a.s.s)
    if re.fullmatch(r"(?:[A-Za-z0-9][^\w\s]+)+[A-Za-z0-9]", token):
        return re.sub(r"[^\w]", "", token).lower()
    # Case 2: normal word
    return token.lower()

def split_into_tokens(text: str) -> list[str]:
    """
    Split text into tokens for profanity filtering:
    - words (letters/numbers with optional embedded symbols, like f*ck, sh!t, f>u>c>k)
    - separators (spaces, punctuation, etc.)
    """
    # Words: letters/numbers with optional non-space symbols inside
    # Separators: whitespace or punctuation
    raw_tokens = re.findall(r"[A-Za-z0-9](?:[^\w\s]{0,2}[A-Za-z0-9])*|\s+|[^\w\s]", text)

    tokens = []
    for t in raw_tokens:
        if re.match(r"[A-Za-z0-9]", t):  # word-like
            tokens.append(_normalize_token(t))
        else:  # keep spaces/punctuation as-is
            tokens.append(t)
    return tokens

def to_hash_mask(text: str, whitelist: str = " .,!?;:'\"()-") -> str:
    """replace all non-whitelisted (punctuation and spaces) characters in the given text with a hash (#)"""
    return ''.join(c if c in whitelist else '#' for c in text)

def levenshtein(a: str, b: str) -> int:
    """compute Levenshtein edit distance between two strings"""
    if len(a) < len(b):
        return levenshtein(b, a)

    if len(b) == 0:
        return len(a)

    prev_row = list(range(len(b) + 1))
    for i, c1 in enumerate(a):
        curr_row = [i + 1]
        for j, c2 in enumerate(b):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]

def count_words(text: str) -> int:
    """
    counts words in a string. words are sequences of letters/numbers
    separated by spaces or punctuation
    """
    tokens = split_into_tokens(text)
    words = [t for t in tokens if t and t.isalnum()]
    return len(words)