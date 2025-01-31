import re
from lve.prompt import Role

def extract_variables_from_prompt(prompt):
    variables = {}
    for msg in prompt:
        if msg.role == Role.assistant:
            varname = msg.variable
            if varname is None:
                varname = str(len(variables))
            variables[varname] = msg.content
    return variables


class CheckerRegistryHolder(type):

    CHECKER_REGISTRY = {}

    def __new__(cls, name, bases, attrs):
        new_cls = type.__new__(cls, name, bases, attrs)
        cls.CHECKER_REGISTRY[name] = new_cls
        return new_cls

    @classmethod
    def get_checker_registry(cls):
        return dict(cls.CHECKER_REGISTRY)
    

class BaseChecker(metaclass=CheckerRegistryHolder):
    
    def __init__(self, prompt_contains_responses=False, get_variables=False, get_response=True):
        self.prompt_contains_responses = prompt_contains_responses
        self.get_variables = get_variables
        self.get_response = get_response 
        
    def invoke_check(self, prompt_in, prompt_out, param_values=None):
        """ Calls the correct signature of is_safe based on the configuration.
            Main function exposed to the lve internals, but not the user.
            
            Args:
                prompt_in: The chat corresponding to the input.
                prompt_out: The chat including model responses.
                param_values: The parameter values plugged into the prompt.
            
            Returns:
                is_safe: Whether the response is safe as determined by is_safe.
                response_or_variables: If there is only one response, returns the response as string, else returns all variables as a dictionary.
        """
        kwargs = {}
        kwargs["prompt"] = prompt_in if self.prompt_contains_responses else prompt_out
        cnt_variables = sum(p.role == Role.assistant for p in prompt_out)
        response = prompt_out[-1].content
        response_or_variables = response

        if self.get_response:
            kwargs["response"] = response

        if self.get_variables or cnt_variables > 1:
            variables = extract_variables_from_prompt(prompt_out) 
            if self.get_variables:
                kwargs["variables"] = variables  
            if cnt_variables > 1:
                response_or_variables = variables

        kwargs["param_values"] = param_values
        return self.is_safe(**kwargs), response_or_variables

    def is_safe(self, prompt, response, param_values=None) -> bool:
        """Determins whether the response is safe given the prompt and the parameters.

        Args:
            prompt: The prompt corresponding to the test.
            response: The response generated by the model.
            param_values: The parameter values plugged into the prompt.
        """
        raise NotImplementedError

    def postprocess_response(self, response):
        """Postprocess response (e.g. to remove bad words or PII)

        Args:
            response: The response generated by the model.
        """
        return response


class LambdaChecker(BaseChecker):
    """Checker which uses a lambda function to check safety."""

    def __init__(self, func):
        super().__init__()
        self.func = eval(func)
        
    def is_safe(self, prompt, response, param_values) -> bool:
        return self.func(response, **param_values)

class NumberChecker(BaseChecker):
    """
    Checker which uses a lambda to compute an expected number that is 
    compared to the model response, normalizing the number format first.
    """

    def __init__(self, expected_value_func):
        super().__init__()
        self.expected_value_func = eval(expected_value_func)
        
    def normalize_number(self, number):
        number = str(number)
        if number.endswith(".0"):
            number = number[:-2]
        return number

    def is_safe(self, prompt, response, param_values) -> bool:
        expected = self.expected_value_func(**param_values)
        return self.normalize_number(response) == self.normalize_number(expected)

class RegexChecker(BaseChecker):
    """Checker which judges safety based on whether ther response matches given pattern."""

    def get_flag(self, flag):
        if flag == "A" or flag == "ASCII":
            return re.ASCII
        elif flag == "I" or flag == "IGNORECASE":
            return re.IGNORECASE
        elif flag == "L" or flag == "LOCALE":
            return re.LOCALE
        elif flag == "M" or flag == "MULTILINE":
            return re.MULTILINE
        elif flag == 'DOTALL':
            return re.DOTALL
        
        raise ValueError(f"Unknown regex flag {flag}")

    def __init__(self, pattern, match_safe, flags=0):
        super().__init__()
        
        if flags != 0:
            flags = self.get_flag(flags)

        self.pattern = re.compile(pattern, flags=flags)
        self.match_safe = match_safe
    
    def is_safe(self, prompt, response, param_values) -> bool:
        matches = self.pattern.search(response) is not None
        return matches == self.match_safe
