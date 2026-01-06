"""
profanity utilities, with three layers of classes to detect profanity:

1. ProfanityCheck (RECOMMENDED)
utilizes a library (https://pypi.org/project/profanity-check/). this is the best, and most accurate way to detect profanity. it uses a machine learning model to detect profanity, and is very good at detecting misspellings and variations of bad words.

2. ProfanityExtralist
this is a small list of bad words that the profanity-check library misses, like "shlt".
this isn't recommended as a primary way to detect profanity, but is a good extra layer.
this is very sensitive, and may catch things that are not bad words. if you find another word that should be added to the whitelist, tell me!!!

3. ProfanityLonglist
this is a large list of bad words, and is very sensitive. it will catch any word that contains a bad word as a substring.
this is NOT recommended as a primary way to detect profanity, but is a good extra layer.
this is very sensitive, and may catch things that are not bad words. if you find another word that should be added to the longlist, tell me!!!
this list is taken directly from Minecraft's banned words list, and is base64 encoded.

the recommended way to use this is to first check with the profanity-check library, then the extralist (and maybe the longlist)
"""
from profanity_check import predict, predict_prob 
from .general_utils import split_into_tokens, levenshtein
import base64

# this works in two ways, using the profanity-check library, and a custom badwords list (which is very small, and includes words that profanity-check misses like "bith" (bitch) and "shlt" (shit)

from .words import blacklist
from .words import whitelist
from .words import longlist as unlonglisted # base64 encoded swear words
_longlist = [
    w.strip().lower()
    for w in base64.b64decode(unlonglisted).decode("utf-8", errors="ignore").splitlines()
    if w.strip()
]


class ProfanityFilter:
    def is_profane(self, text: str) -> bool:
        raise NotImplementedError

    def censor(self, text: str, replacement: str = "#") -> str:
        raise NotImplementedError


# extralist
class ProfanityExtralist(ProfanityFilter):
    def is_profane(self, text: str) -> bool:
        """
        checks a string if it has any word found in the extra blacklist in words.py

        note that this is NOT a replacement for the other like the profanity-check ones, and this is an extra list because profanity-check doesn't see things like "shlt"

        Args:
            text (str): input string to check.
        """
        tokens = split_into_tokens(text); tokens = [t.lower() for t in tokens] # split into words + separators

        for token in tokens:
            for bad in blacklist:
                if token in whitelist: # only check if it's not whitelisted
                    continue

                # Rule 1: fuzzy match full word
                dist = levenshtein(token, bad)
                if dist <= max(1, len(bad) // 1.3):
                    return True

                # Rule 2: substring fuzzy match if lengths are close
                if abs(len(token) - len(bad)) <= 5:
                    for j in range(0, len(token) - len(bad) + 1):
                        chunk = token[j:j+len(bad)]
                        dist = levenshtein(chunk, bad)
                        if dist <= max(1, len(bad) // 2):
                            return True

        return False

    def censor(self, text: str, replacement: str = "#", neighbors: int = 1) -> str:
        """
        censors words found in the extra word list things profanity-check misses, checking word-by-word
        
        note that this is NOT a replacement for the other like the profanity-check ones, and this is an extra list because profanity-check doesn't see things like "shlt"

        Args:
            text (str): the input text to censor.
            replacement (str, optional): character to use for censoring. defaults to '#' (ROBLOX!!!).
            neighbors (int, optional): number of neighboring words to also censor. defaults to 1 (no neigboring word touched).

        Returns:
            str: the censored text
        """
        tokens = split_into_tokens(text)
        lowered = [t.lower() for t in tokens]
        n = len(tokens)
        censored = [False] * n

        for i, token in enumerate(tokens):
            if token.isalnum() and self.is_profane(token):
                censored[i] = True

                # neighbor logic
                j, words_seen = i, 0
                while j > 0 and words_seen < neighbors:
                    j -= 1
                    if lowered[j].isalnum():
                        censored[j] = True
                        words_seen += 1

                j, words_seen = i, 0
                while j < n - 1 and words_seen < neighbors:
                    j += 1
                    if lowered[j].isalnum():
                        censored[j] = True
                        words_seen += 1

        # Build censored output
        censored_tokens = [
            (replacement * len(t)) if censored[i] and lowered[i].isalnum() else t
            for i, t in enumerate(tokens)
        ]

        return "".join(censored_tokens)


# longlist
class ProfanityLonglist(ProfanityFilter):
    def is_profane(self, text: str) -> bool:
        """
        checks for profanity in the extra longlist of profanities, returns true anything is found

        note that this is NOT a replacement for the other like the profanity-check ones, and this is an extra list because profanity-check doesn't see things like "shlt"
        """
        tokens = split_into_tokens(text); tokens = [t.lower() for t in tokens] # split into words + separators, then lower

        # check for bad words, return true if even just one is found
        for token in tokens:
            for bad in _longlist:
                if bad in token:
                    return True
        return False
                
    def censor(self, text: str, replacement: str = "#", neighbors: int = 1) -> str:
        """
        Censors words found in the extra longlist of profanities, replacing them and their neighbors.

        note that this is NOT a replacement for the other like the profanity-check ones, and this is an extra list because profanity-check doesn't see things like "shlt"

        Args:
            text (str): the input text to censor.
            replacement (str, optional): character to use for censoring. Defaults to '#'.
            neighbors (int, optional): number of words in the censoring window, including the bad word itself

        Returns:
            str: the censored text.
        """
        def is_word_token(tok: str) -> bool:
            # treat as a word if it contains at least one alphabetic character
            return any(ch.isalpha() for ch in tok)

        # tokenize + lowercase in place
        tokens = split_into_tokens(text); tokens = [t.lower() for t in tokens]
        n = len(tokens)
        censored = [False] * n

        for i, token in enumerate(tokens):
            if is_word_token(token):
                for bad in _longlist:
                    if bad in token:
                        # way better checking but i don't wanna put this in is_profane_longlist

                        # always censor the bad word itself
                        censored[i] = True

                        # extend left (neighbors - 1 words)
                        j, words_seen = i, 0
                        while j > 0 and words_seen < neighbors - 1:
                            j -= 1
                            if is_word_token(tokens[j]):
                                censored[j] = True
                                words_seen += 1

                        # extend right (neighbors - 1 words)
                        j, words_seen = i, 0
                        while j < n - 1 and words_seen < neighbors - 1:
                            j += 1
                            if is_word_token(tokens[j]):
                                censored[j] = True
                                words_seen += 1
                        break  # stop after first badword match

        # rebuild text with censored replacements
        result_tokens = []
        for token, flag in zip(tokens, censored):
            if flag and is_word_token(token):
                result_tokens.append(replacement * len(token))
            else:
                result_tokens.append(token)

        return "".join(result_tokens)


# profanity-check
class ProfanityCheck(ProfanityFilter):
    def is_profane(self, text: str) -> bool:
        """
        check if the given text contains profanity
        """
        tokens = split_into_tokens(text)
        normalized_text = "".join(tokens)  # join tokens back into a single string
        return bool(predict([normalized_text])[0])

    def censor(self, text: str, censor_char: str = "#", neighbors: int = 1, window_size: int = 1) -> str:
        """
        Censors profane words using a sliding window.
        Works directly on tokens from split_into_tokens.
        """
        raw_tokens = split_into_tokens(text)             # includes words + separators
        lowered_tokens = [t.lower() for t in raw_tokens] # normalized for detection
        n = len(lowered_tokens)

        # build sliding windows
        windows = [" ".join(lowered_tokens[i:i+window_size]) for i in range(n)]
        predictions = predict(windows)

        censored = [False] * n

        for i, flag in enumerate(predictions):
            if flag == 1:
                start = max(0, i - neighbors)
                end = min(n, i + window_size + neighbors)
                for j in range(start, end):
                    censored[j] = True

        # censor words only, keep separators intact
        censored_tokens = [
            (censor_char * len(tok)) if censored[i] and tok.strip() and not tok.isspace() else tok
            for i, tok in enumerate(raw_tokens)
        ]

        return "".join(censored_tokens)
