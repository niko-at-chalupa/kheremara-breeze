from detoxify import Detoxify

# each model takes in either a string or a list of strings
#results = Detoxify('original').predict('example text')
#results = Detoxify('unbiased').predict(['example text 1','example text 2'])

# to specify the device the model will be allocated on (defaults to cpu), accepts any torch.device input

model = Detoxify('unbiased', device='cpu')

def round_and_dict_to_list(dict) -> list[tuple[str, float]]:
    """
    quick way to both convert the dict to a list of tuples and round the floats to the thousandths place

    Args:
        dict (dict): Dictionary to convert & round

    Example:
        >>> round_and_dict_to_list({'toxicity': 0.123456, 'severe_toxicity': 0.654321})
        [('toxicity', 0.123), ('severe_toxicity', 0.654)]
    """
    return [(k, round(float(v), 3)) for k, v in dict.items()]

def detoxify_text(text: str, model='unbiased') -> dict:
    """
    runs Detoxify on the provided text and returns the results as a dictionary (a wrapper for Detoxify(model).predict(text))

    Args:
        text (str): Text to analyze
        model (str, optional): model to use. defaults to 'unbiased'. options are 'original', 'unbiased', 'multilingual', and 'multilingual-v2'.

    Returns: 
        dict: dictionary of results from Detoxify (i like to just feed this into round_and_dict_to_list to make it WAY easier to work with)

    Example:
        >>> detoxify_text("example text", model='unbiased')
        {'toxicity': np.float32(0.9977558), 'severe_toxicity': np.float32(0.4578004), 'obscene': np.float32(0.9929531), 'threat': np.float32(0.0037068268), 'insult': np.float32(0.9531659), 'identity_attack': np.float32(0.015627943)}
    """
    return Detoxify(model).predict(text)

def is_toxic_text(data: list, threshold=0.540) -> bool:
    """
    quick way to determine if text is harmful in any way based on the provided threshold (defaults to 0.540, which is what i just like to use)

    Args:
        data (list): list of tuples from round_and_dict_to_list()
        threshold (float, optional): threshold to use. defaults to 0.540.

    Returns:
        bool: True if any of the values are above the threshold, False otherwise

    Example:
        >>> is_toxic_text(round_and_dict_to_list(detoxify_text("I hate you!!")))
        True
    """
    # if any of the values are above the threshold, return True (indicating harmful content)
    for k, v in data:
        if v >= threshold:
            return True
    return False

def is_toxic_text_advanced(data: list, threshold=0.540) -> list[tuple[str, bool]]:
    """
    like is_toxic_text but returns a list of tuples indicating which categories are above the threshold

    Args:
        data (list): list of tuples from round_and_dict_to_list()
        threshold (float, optional): threshold to use. defaults to 0.540.

    Returns:
        list[tuple[str, bool]]: list of tuples indicating which categories are above the threshold

    Example:
        >>> is_toxic_text_advanced(round_and_dict_to_list(detoxify_text("I hate you!!")))
        [('toxicity', True), ('severe_toxicity', False), ('obscene', False), ('identity_attack', False), ('insult', False), ('threat', False), ('sexual_explicit', False)]
    """
    results = []
    for k, v in data:
        results.append((k, v >= threshold))
    return results