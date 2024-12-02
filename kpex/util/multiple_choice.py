from __future__ import annotations
from functools import cached_property
from typing import *


class MultipleChoicePattern:
    def __init__(self, pattern: str):
        """
        Multiple Choice pattern, allows blacklisting and whitelisting.
        For example, given a list of dielectric, let the user decide which of them to include or exclude.
        Allowed patterns:
            - all (default): complete list of choices included
            - none: no choices included at all
            - +dielname: include choice named 'dielname'
            - -dielname: exclude choice named 'dielname'
        Examples:
            - all,-nild5,-nild6
               - include all dielectrics except nild5 and nild6
            - none,+nild5,+capild
                - include only dielectrics named nild5 and capild
        """
        self.pattern = pattern

        components = pattern.split(sep=',')
        components = [c.lower().strip() for c in components]
        self.has_all = 'all' in components
        self.has_none = 'none' in components
        self.included = [c[1:] for c in components if c.startswith('+')]
        self.excluded = [c[1:] for c in components if c.startswith('-')]
        if self.has_none and self.has_all:
            raise ValueError("Multiple choice pattern can't have both subpatterns all and none")
        if self.has_none and len(self.excluded) >= 1:
            raise ValueError("Multiple choice pattern based on none can only have inclusive (+) subpatterns")
        if self.has_all and len(self.included) >= 1:
            raise ValueError("Multiple choice pattern based on all can only have exclusive (-) subpatterns")

    def filter(self, choices: List[str]) -> List[str]:
        if self.has_all:
            return [c for c in choices if c not in self.excluded]
        return [c for c in choices if c in self.included]

    def is_included(self, choice: str) -> bool:
        if self.has_none:
            return choice in self.included
        if self.has_all:
            return choice not in self.excluded
        return False