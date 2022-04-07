from easyila.guidance import Guidance, AnnoType
from easyila.synthesis_template import *

class TestGuidance:

    def test_guard_annotation(self):
        pc_sig = S("Tile","pc", 32)
        a_sig = S("Tile", "a", 32)
        signals = [
            S("Tile", "reset", 1),
            pc_sig,
            a_sig,
            S("Tile", "b", 32),
        ]
        guidance = Guidance(signals, 10)
        guidance.annotate("reset", AnnoType.ASSUME)
        # Maps predicates to corresponding AnnoType
        guidance.annotate("a", {
            pc_sig.to_variable().op_eq(6): AnnoType.PARAM,
            smt.BoolConst.T: AnnoType.DONT_CARE,
        })
        guidance.annotate("b", {
            pc_sig.to_variable().op_eq(6): AnnoType.ASSUME,
            pc_sig.to_variable().op_eq(7): AnnoType.PARAM,
            pc_sig.to_variable().op_eq(8): AnnoType.OUTPUT,
            smt.BoolConst.T: AnnoType.ASSUME,
        })
        assert guidance.get_annotation_at("a", 4) is None
        assert guidance.get_predicated_annotations("a") == {
            pc_sig.to_variable().op_eq(6): AnnoType.PARAM,
            smt.BoolConst.T: AnnoType.DONT_CARE,
        }
        assert guidance.get_outputs() == {
            ("Tile->b", pc_sig.to_variable().op_eq(8))
        }

    def test_output_annotations(self):
        signals = [
            S("Tile", "reset", 1),
            S("Tile", "clk", 1),
            S("Tile", "a", 32),
            S("Tile", "b", 32),
            S("Tile", "c", 32),
        ]
        guidance = Guidance(signals, 10)
        guidance.annotate("b", {8: AnnoType.OUTPUT})
        guidance.annotate("c", {9: AnnoType.OUTPUT})
        outputs = guidance.get_outputs()
        assert outputs == {("Tile->b", 8), ("Tile->c", 9)}

    def test_subscript_annotations(self):
        signals = [
            S("tb", "reset", 1),
            S("tb", "clk", 1),
            S("tb", "data", 8, bounds=(0, 7)),
        ]
        guidance = Guidance(signals, 10)
        guidance.annotate("data[0]", {7: AnnoType.PARAM})
        guidance.annotate("data[3]", {3: AnnoType.PARAM})
        assert guidance.get_annotation_at("data[0]", 7) == AnnoType.PARAM
        assert guidance.get_annotation_at("data[0]", 6) == AnnoType.DONT_CARE
        assert guidance.get_annotation_at("data[0]", 8) == AnnoType.DONT_CARE
        assert guidance.get_annotation_at("data[3]", 3) == AnnoType.PARAM
        assert guidance.get_annotation_at("data[3]", 2) == AnnoType.DONT_CARE
        assert guidance.get_annotation_at("data[3]", 4) == AnnoType.DONT_CARE
        assert guidance.get_annotation_at("data[1]", 7) == AnnoType.DONT_CARE

    def test_guidance_iterate(self):
        signals = [
            S("tb", "reset", 1),
            S("tb", "clk", 1),
            S("tb", "data", 8, bounds=(0, 7)),
            S("tb", "a", 8),
            S("tb", "b", 8)
        ]
        guidance = Guidance(signals, 10)
        found_params = set()
        found_assumes = set()
        found_outputs = set()
        guidance.annotate("reset", {0: AnnoType.ASSUME})
        guidance.annotate("a", {3: AnnoType.ASSUME, 7: AnnoType.PARAM})
        guidance.annotate("b", {8: AnnoType.OUTPUT})
        guidance.annotate("data[0]", {7: AnnoType.PARAM})
        guidance.annotate("data[3]", {3: AnnoType.PARAM})
        for cycle in range(guidance.num_cycles):
            for ind, signal in enumerate(guidance.signals):
                for qp in signal.get_all_qp_instances():
                    atype = guidance.get_annotation_at(qp, cycle)
                    if atype == AnnoType.DONT_CARE:
                        pass
                    elif atype == AnnoType.ASSUME:
                        found_assumes.add((qp, cycle))
                    elif atype == AnnoType.PARAM:
                        found_params.add((qp, cycle))
                    elif atype == AnnoType.OUTPUT:
                        found_outputs.add((qp, cycle))
                    else:
                        raise TypeError("invalid AnnoType: " + str(atype))
        assert found_params == {("tb->a", 7), ("tb->data[0]", 7), ("tb->data[3]", 3)}
        assert found_assumes == {("tb->reset", 0), ("tb->a", 3)}
        assert found_outputs == {("tb->b", 8)}
