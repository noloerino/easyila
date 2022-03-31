from collections import defaultdict
from dataclasses import dataclass, field
import textwrap
from typing import List, Dict

import easyila.lynth.smt as smt

"""
An Instruction represents a sequence of state transitions. A transition is a mapping
of state variables to expressions computing their next values.

A single instruction is considered to be atomic.
"""
Instruction = List[Dict[smt.Term, smt.Term]]

# models should look something like this?
# TODO instead of having separate uf/logic/next logic, should they all be values of
# a dict keyed by variables? probably not, because of the splitting behavior of the
# `instructions` array
@dataclass
class Model:
    name: str
    inputs: List[smt.Variable] = field(default_factory=list)
    outputs: List[smt.Variable] = field(default_factory=list)
    state: List[smt.Variable] = field(default_factory=list)
    # TODO variables are just UFs of 0 arity -- should we treat them all the same?
    ufs: List[smt.UFTerm] = field(default_factory=list)
    # memories: List[]
    # how do we incorporate child-ILA transitions? how do we connect modules?
    instances: Dict[str, "Instance"] = field(default_factory=dict)
    """
    Maps instance names to coresponding Model objects. I/O connections should be declared through
    the `logic` field.
    """
    logic: Dict[smt.Term, smt.Term] = field(default_factory=dict)
    """Same-cycle logic expressions."""

    """
    TODO

    TODO account for assignments to memories/arrays in logic and default_next

    should we be able to have multiple submodules of the same instance? this
    has a common use case for stuff like memories that are repeated

    how do we distinguish between having ILA instructions to execute vs.
    having transitions? for now, just have a default "NEXT" instruction
    """
    default_next: Instruction = field(default_factory=list)
    instructions: Dict[str, Instruction] = field(default_factory=dict)
    init_values: Dict[str, smt.BVConst] = field(default_factory=dict)

    def __post_init__(self):
        assert isinstance(self.inputs, list)
        assert isinstance(self.outputs, list)
        assert isinstance(self.state, list)
        assert isinstance(self.ufs, list)
        assert isinstance(self.logic, dict)
        assert isinstance(self.default_next, list)
        assert isinstance(self.instances, dict)
        assert isinstance(self.init_values, dict)

    def validate(self):
        """
        Checks that all expressions are well-typed, variables are declared, etc.
        Returns True on success, False on failure.

        TODO more robust error handling
        """
        errs = []
        def report(s):
            print(f"{self.name}:", s)
            errs.append(s)
        def get_var_counts(l):
            counts = defaultdict(lambda: 0) # maps variable name to appearances in l
            for v in l:
                counts[v.name] += 1
            return counts
        in_counts = get_var_counts(self.inputs)
        out_counts = get_var_counts(self.outputs)
        state_counts = get_var_counts(self.state)
        uf_counts = get_var_counts(self.ufs)
        # Zeroth pass: validate all instances and port bindings
        for subname, sub in self.instances.items():
            if not sub.model.validate():
                report(f"validation error(s) in submodule {subname} (see above output)")
            needed_inputs = sub.model.inputs
            for missing_input in set(needed_inputs) - set(sub.inputs.keys()):
                report(f"instance {subname} is missing binding for input {missing_input}")
            for extra_input in set(sub.inputs.keys()) - set(needed_inputs):
                report(f"instance {subname} has binding for unknown input {extra_input}")
        # First pass: no variable is declared multiple times
        # TODO don't be stateful if isinstance(v, smt.Variable)!
        for s, count in in_counts.items():
            if count > 1:
                report(f"input {s} was declared multiple times")
            if s in out_counts:
                report(f"input {s} was also declared as an output")
            if s in state_counts:
                report(f"input {s} was also declared as a state variable")
            if s in uf_counts:
                report(f"input {s} was also declared as an uninterpreted function")
        for s, count in out_counts.items():
            if count > 1:
                report(f"output {s} was declared multiple times")
            if s in state_counts:
                report(f"output {s} was also declared as a state variable")
            # if s in uf_counts:
            #     report(f"output {s} was also declared as an uninterpreted function")
        for s, count in state_counts.items():
            if count > 1:
                report(f"state variable {s} was declared multiple times")
            if s in uf_counts:
                report(f"output {s} was also declared as an uninterpreted function") 
        for s, count in uf_counts.items():
            if count > 1:
                report(f"uninterpreted function {s} was declared multiple times")
        # Second pass: all state and output have assigned expressions xor transition relations
        # and that inputs + UFs do NOT have declared logic
        # TODO for now, outputs can also be UFs
        logic_and_next = {v.name for v in self.logic if isinstance(v, smt.Variable)}
        next_keys = set()
        for l in self.default_next:
            names = {v.name for v in l if isinstance(v, smt.Variable)}
            next_keys.update(names)
            logic_and_next.update(names)
        for v in self.inputs:
            if v.name in self.logic:
                report(f"input variable {v.name} has illegal declared logic")
            if v.name in next_keys:
                report(f"input variable {v.name} has illegal declared transition relation")
        for v in self.state:
            if not isinstance(v.sort, smt.ArraySort) and v.name not in logic_and_next:
                report(f"state variable {v.name} has no declared logic or transition relation")
        for v in self.outputs:
            if v.name not in logic_and_next and v.name not in uf_counts:
                report(f"output variable {v.name} has no declared logic or transition relation")
        for v in self.ufs:
            if v.name in self.logic:
                report(f"uninterpreted function {v.name} has illegal declared logic")
            if v.name in next_keys:
                report(f"uninterpreted function {v.name} has illegal declared transition relation")
        # nth pass: init values correspond to valid variables
        # TODO
        # nth pass: transition relations and expressions type check and are valid
        for v, e in self.logic.items():
            if not e.typecheck():
                report(f"type error in logic for {v} (see above output)")
        for l in self.default_next:
            for v, e in l.items():
                if not e.typecheck():
                    report(f"type error in transition logic for {v} (see above output)")
        return len(errs) == 0

    def pretty_str(self, indent_level=0):
        # Weird things happen with escaped chars in f-strings
        newline = '\n' + ' ' * 20
        c_newline = "," + newline
        if len(self.inputs) > 0:
            input_block = newline + c_newline.join([str(a.get_decl()) for a in self.inputs])
        else:
            input_block = ""
        if len(self.outputs) > 0:
            output_block = newline + c_newline.join([str(a.get_decl()) for a in self.outputs])
        else:
            output_block = ""
        if len(self.state) > 0:
            state_block = newline + c_newline.join([str(a.get_decl()) for a in self.state])
        else:
            state_block = ""
        if len(self.ufs) > 0:
            uf_block = newline + c_newline.join([str(a) for a in self.ufs])
        else:
            uf_block = ""
        if len(self.instances) > 0:
            inst_block = newline + c_newline.join(str(m) + ':' + i.pretty_str(24) for m, i in self.instances.items())
        else:
            inst_block = ""
        if len(self.logic) > 0:
            logic_block = newline + c_newline.join(str(m) + ': ' + str(e) for m, e in self.logic.items())
        else:
            logic_block = ""
        if len(self.default_next) > 0:
            next_block = newline + c_newline.join(str(m) + ': ' + str(e) for m, e in self.default_next[0].items())
        else:
            next_block = ""
        return textwrap.indent(textwrap.dedent(f"""\
            Model(
                name="{self.name}",
                inputs={input_block},
                outputs={output_block},
                state={state_block},
                ufs={uf_block},
                instances={inst_block},
                logic={logic_block},
                default_next={next_block},
                instructions={self.instructions},
                init_values={self.init_values},
            )"""
        ), ' ' * indent_level)

    def print(self):
        print(self.pretty_str())

    def to_uclid(self):
        u_vars = []
        def u_append(lst, prefix):
            nonlocal u_vars
            if len(lst) > 0:
                u_vars.extend(prefix + " " + str(s.get_decl()) + ";" for s in lst)
        u_append(self.inputs, "input")
        u_append(self.outputs, "output")
        u_append(self.state, "var")
        if len(self.ufs) > 0:
            u_vars.extend(s.to_uclid() for s in self.ufs)
        newline = ' ' * 16
        u_vars_s = textwrap.indent("\n".join(u_vars), newline)
        instances_s = textwrap.indent("\n".join(i.to_uclid(n) for n, i in self.instances.items()), newline)
        logic_s = textwrap.indent(
            "\n".join(f"{lhs.to_uclid()} = {rhs.to_uclid()};" for lhs, rhs in self.logic.items()),
            newline + "    "
        )
        if len(self.default_next) > 0:
            next_s = textwrap.indent(
                "\n".join(f"{lhs.to_uclid()}' = {rhs.to_uclid()};" for lhs, rhs in self.default_next[0].items()),
                newline + "    "
            )
        else:
            next_s = newline
        if len(self.instances) > 0:
            child_next_s = textwrap.indent(
                "\n".join(f"next({n});" for n in self.instances),
                newline + "    "
            )
        return textwrap.dedent(f"""\
            module {self.name} {{
{u_vars_s}

{instances_s}

                init {{

                }}

                next {{
                    // Combinatorial logic
{logic_s}
                    // Transition logic
{next_s}
                    // Instance transitions
{child_next_s}
                }}
            }}""")


@dataclass
class Instance:
    """
    A class representing the concrete instantiation of a model.

    Input bindings are represented in the `inputs` field.

    Output bindings are specified only by the parent module.
    """

    model: Model
    inputs: Dict[smt.Variable, smt.Term]
    """
    Maps UNQUALIFIED input names to an expression in the parent module (all variable references
    within the expression are relative to that parent.)
    """

    def pretty_str(self, indent_level=0):
        newline = '\n' + ' ' * 12
        c_newline = "," + newline
        if len(self.inputs) > 0:
            input_block = newline + c_newline.join(str(v) + ": " + str(e) for v, e in self.inputs.items())
        else:
            input_block = ""
        # maybe there's a cleaner way to do this f string :)
        return textwrap.indent(textwrap.dedent(f"""\

            input_bindings={input_block},
            model:
{self.model.pretty_str(16)}"""),
            ' ' * indent_level
        )

    def to_uclid(self, instance_name):
        newline = ",\n" + (' ' * 16)
        i_lines = (' ' * 16) + newline.join(
            f"{lhs.name} : ({rhs.to_uclid()})" for lhs, rhs in self.inputs.items()
        )
        return textwrap.dedent(f"""\
            instance {instance_name} : {self.model.name}
            (
{i_lines}
            );""")


class CaseSplitModel(Model):
    ...

@dataclass
class SyntaxGeneratedModel(Model):
    """
    A model generated by parsing a verilog file.

    State variables correspond to RTL registers, and transitions are
    automatically parsed.
    """
    def __init__(self, verilog_file):
        # TODO
        ...

@dataclass
class SynthesizedModel(Model):
    """
    A model with components generated by SyGuS.

    TODO figure out how to compose this
    """
    def __init__(self):
        ...
