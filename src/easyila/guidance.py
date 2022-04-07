"""
Annotations that provide guidance for oracles.
"""

from collections import defaultdict
from enum import Enum
from typing import Dict, List, Tuple, Set, Optional, Union

import easyila.lynth.smt as smt

class AnnoType(Enum):
    """
    Types of annotations
    """
    DONT_CARE = 0
    ASSUME = 1
    PARAM = 2
    OUTPUT = 3

class Guidance:
    """
    Allows the user to provide guidance for whether or not a value at a particular clock cycle
    is DONT_CARE ("Don't Care"), ASSUME ("Assumed" to be the value read during simulation), PARAM
    ("Parameter" of the synthesis function), or OUTPUT ("Output" of the synthesis function).
    """

    def __init__(self, signals, num_cycles: int):
        self.signals = signals
        self.signal_names = [qpath for s in self.signals for qpath in s.get_all_qp_instances()]
        self.base_names = [basename for s in self.signals for basename in s.get_all_bp_instances()]
        self.base_to_qualified = dict(zip(self.base_names, self.signal_names))
        self.num_cycles = num_cycles
        # Maps qualified signal names to maps of cycle -> AnnoType
        # OR maps of smt.Term -> AnnoType
        self._guide_dict: Dict[str, Union[Dict[int, AnnoType], Dict[smt.Term, AnnoType]]] = defaultdict(lambda: defaultdict(lambda: AnnoType.DONT_CARE))

    def _validate_signame(self, signal):
        if not isinstance(signal, str):
            raise TypeError(f"Guidances are keyed by signal name, instead got {signal}")
        if signal not in self.signal_names:
            signal = self.base_to_qualified[signal]
            if signal not in self.signal_names:
                raise KeyError(signal)
        return signal

    def annotate(self, signal, annotation):
        """
        Specify annotations.

        If the argument is a list, then treat it as a cycle-by-cycle description
        of annotations.

        If the argument is a dict of ints, then just copy it.

        If the argument is a dict mapping smt.Term to AnnoType, it is copied as well.
        These predicates will be turned into an if/elseif tree, so if two conditions
        are true, only the first will matter.

        If the argument is an AnnoType, then apply that AnnoType for every cycle,
        overwriting any existing annotations.
        """
        signal = self._validate_signame(signal)
        if isinstance(annotation, list):
            for t, g in enumerate(annotation):
                self._guide_dict[signal][t] = g
        elif isinstance(annotation, dict):
            first_key = list(annotation.keys())[0]
            own_dict = self._guide_dict[signal]
            if isinstance(first_key, int):
                if len(own_dict) and isinstance(list(own_dict.keys())[0], smt.Term):
                    raise Exception("Cannot update guidance for predicated signal with cycle count")
                own_dict.update(annotation)
            elif isinstance(first_key, smt.Term):
                if len(own_dict) and isinstance(list(own_dict.keys())[0], int):
                    raise Exception("Cannot update guidance for cycle count sampled signal with predicate")
                own_dict.update(annotation)
            else:
                raise Exception(f"Cannot interpret annotation: {annotation}")
        elif isinstance(annotation, AnnoType):
            self._guide_dict[signal] = defaultdict(lambda: annotation)
        else:
            raise Exception(f"Cannot interpret annotation: {annotation}")

    def get_annotation_at(self, signal, cycle) -> Optional[AnnoType]:
        """
        Gets the appropriate annotation for `signal` on the corresponding `cycle`.
        If the signal's annotations are instead specified by predicates, then None is returned.
        """
        signal = self._validate_signame(signal)
        if cycle >= self.num_cycles:
            raise IndexError(f"cycle {cycle} exceeds num_cycles {self.num_cycles}")
        own_dict = self._guide_dict[signal]
        if len(own_dict) and isinstance(list(own_dict.keys())[0], smt.Term):
            return None
        return own_dict[cycle]

    def get_predicated_annotations(self, signal) -> Dict[smt.Term, AnnoType]:
        """
        Returns a dict of all predicate-based annotations for this signal.
        """
        signal = self._validate_signame(signal)
        own_dict = self._guide_dict[signal]
        if len(own_dict) and isinstance(list(own_dict.keys())[0], smt.Term):
            return own_dict
        else:
            return {}

    def get_outputs(self) -> Set[Tuple[str, Union[int, smt.Term]]]:
        """
        Returns (signal name | condition, cycle number) pairs representing all annotated outputs.
        """
        outputs = set()
        for signal, cycles in self._guide_dict.items():
            outputs.update({(signal, n) for n in cycles if cycles[n] == AnnoType.OUTPUT})
        return outputs
