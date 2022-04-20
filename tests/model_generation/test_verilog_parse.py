
import textwrap

import pytest

import easyila.lynth.smt as smt
from easyila.verilog import verilog_to_model, COIConf
from easyila.model import Model, Instance, UFPlaceholder

class TestVerilogParse:
    """
    Tests generation of Models from Verilog files.

    On the current version of pyverilog, initial register values are not treated properly, hence
    the need for a reset input.

    pyverilog "if" branches that are missing an "else" block also will produce a dummy "dest" variable
    when `tocode` is called, though this does not affect the actual dataflow graph.
    """

    def test_verilog_single_noimp(self):
        """
        Tests model generation of a model from a single RTL module.
        No "important" values are specified. "_rn" signals for intermediate values
        generated by pyverilog are kept.

        Rename inlining is off, meaning they should appear in the output.
        """
        rtl = textwrap.dedent("""\
            module top(input clk, input should_inc, output [2:0] result);
                reg [2:0] a;
                wire [2:0] a_p1;
                always @(posedge clk) begin
                    if (should_inc) begin
                        a = a_p1;
                    end
                end
                assign a_p1 = a + 3'h1;
                assign result = ~a;
            endmodule
            """
        )
        model = verilog_to_model(rtl, "top", inline_renames=False)
        model.print()
        bv3 = smt.BVSort(3)
        var = smt.Variable
        a = var("a", bv3)
        rn_a = var("_rn0_a", bv3)
        a_p1 = var("a_p1", bv3)
        should_inc = smt.BoolVariable("should_inc")
        assert model == \
            Model(
                "top",
                inputs=[should_inc],
                outputs=[var("result", bv3)],
                state=[a, a_p1, rn_a],
                logic={
                    a_p1: a + 1,
                    rn_a: a_p1,
                    var("result", bv3): ~a,
                },
                default_next={a: should_inc.ite(rn_a, a)},
            )

    def test_verilog_always_star(self):
        """
        Tests that dependencies from always @* blocks are placed in the correct cycle.

        Also implicitly tests inlining of "rename" variables.
        """
        rtl = textwrap.dedent("""\
            module top(input clk, input in);
                reg r0;
                reg r1;
                always @(posedge clk) begin
                    r0 = r0 | in;
                end
                always @* begin
                    r1 = r1 | in;
                end
            endmodule
            """)
        model = verilog_to_model(rtl, "top", inline_renames=True)
        model.print()
        in_ = smt.BoolVariable("in")
        r0 = smt.BoolVariable("r0")
        r1 = smt.BoolVariable("r1")
        assert model == \
            Model(
                "top",
                inputs=[in_],
                state=[r0, r1],
                logic={r1: r1 | in_},
                default_next={r0: r0 | in_}
            )

    def test_verilog_single_imp_no_coi(self):
        """
        Tests generation of a model from a single RTL module with specified important signals.
        `coi_conf` is `NO_COI`, meaning non-important signals are 1-arity UFs with a single argument
        for degrees of freedom.
        """
        rtl = textwrap.dedent("""\
            module top(input clk, input should_inc, output [2:0] result);
                reg [2:0] a;
                reg [2:0] b;
                wire [2:0] a_p1;
                wire [2:0] b_p1;
                always @(posedge clk) begin
                    if (should_inc) begin
                        a = a_p1;
                        b = b_p1;
                    end
                end
                assign a_p1 = a + 3'h1;
                assign b_p1 = b + 3'h1;
                assign result = ~a | ~b;
            endmodule
            """)
        bv3 = smt.BVSort(3)
        var = smt.Variable
        # TODO to allow for composition of child modules, and specifying important_signals for those
        model_no_a = verilog_to_model(rtl, "top", important_signals=["should_inc", "b", "b_p1", "result"])
        model_no_a.print()
        a = var("a", bv3)
        a_p1 = var("a_p1", bv3)
        b = var("b", bv3)
        b_p1 = var("b_p1", bv3)
        should_inc = var("should_inc", smt.BoolSort())
        result = var("result", bv3)
        assert model_no_a.validate()
        assert model_no_a == \
            Model(
                "top",
                inputs=[should_inc],
                outputs=[result],
                state=[b, b_p1],
                # `a` appears in the expression for `result`, but is not declared important
                # therefore, it is modeled as a 1-arity uninterpreted function
                ufs=[UFPlaceholder("a", bv3, (), True)],
                logic={
                    b_p1: b + 1,
                    result: (~a) | (~b)
                },
                default_next={b: should_inc.ite(b_p1, b)},
            )
        model_no_b = verilog_to_model(rtl, "top", important_signals=["should_inc", "a", "a_p1", "result"])
        assert model_no_b.validate()
        assert model_no_b == \
            Model(
                "top",
                inputs=[should_inc],
                outputs=[result],
                state=[a, a_p1],
                # `b` appears in the expression for `result`, but is not declared important
                # therefore, it is modeled as a 1-arity uninterpreted function
                ufs=[UFPlaceholder("b", bv3, (), True)],
                logic={
                    a_p1: a + 1,
                    result: (~a) | (~b)
                },
                default_next={a: should_inc.ite(a_p1, a)},
            )

    def test_verilog_single_imp_uf_coi_logic(self):
        """
        Tests generation of a model from a single RTL module with specified important signals.
        `coi_conf` is `UF_ARGS_COI`, meaning that non-important signals are replaced with uninterpreted
        functions. Unlike `NO_COI`, these UF terms have important arguments in their COI as arguments.
        """
        rtl = textwrap.dedent("""\
            module top(input clk, input should_inc, output [2:0] result);
                reg [2:0] a;
                reg [2:0] b;
                wire [2:0] a_p1;
                wire [2:0] b_p1;
                always @(posedge clk) begin
                    if (should_inc) begin
                        a = a_p1;
                        b = b_p1;
                    end
                end
                assign a_p1 = a + 3'h1;
                assign b_p1 = b + 3'h1;
                assign result = ~a | ~b;
            endmodule
            """)
        bv3 = smt.BVSort(3)
        var = smt.Variable
        model_no_a = verilog_to_model(
            rtl,
            "top",
            important_signals=["should_inc", "b", "b_p1", "result"],
            coi_conf=COIConf.UF_ARGS_COI,
        )
        model_no_a.print()
        a = var("a", bv3)
        a_p1 = var("a_p1", bv3)
        b = var("b", bv3)
        b_p1 = var("b_p1", bv3)
        should_inc = var("should_inc", smt.BoolSort())
        result = var("result", bv3)
        assert model_no_a.validate()
        assert model_no_a == \
            Model(
                "top",
                inputs=[should_inc],
                outputs=[result],
                state=[b, b_p1],
                # `a` appears in the expression for `result`, but is not declared important
                # therefore, it is modeled as an uninterpreted function
                ufs=[UFPlaceholder("a", bv3, (should_inc,), True)],
                logic={
                    b_p1: b + 1,
                    result: (~a) | (~b)
                },
                default_next={b: should_inc.ite(b_p1, b)},
            )
        model_no_b = verilog_to_model(
            rtl,
            "top",
            important_signals=["should_inc", "a", "a_p1", "result"],
            coi_conf=COIConf.UF_ARGS_COI,
        )
        assert model_no_b.validate()
        assert model_no_b == \
            Model(
                "top",
                inputs=[should_inc],
                outputs=[result],
                state=[a, a_p1],
                # `b` appears in the expression for `result`, but is not declared important
                # therefore, it is modeled as an uninterpreted function
                # TODO namespace collision for should_inc parameter?
                ufs=[UFPlaceholder("b", bv3, (should_inc,), True)],
                logic={
                    a_p1: a + 1,
                    result: (~a) | (~b)
                },
                default_next={a: should_inc.ite(a_p1, a)},
            )

    def test_verilog_single_imp_uf_coi_temporal_state(self):
        """
        Tests generation of a model from a single RTL module with specified important signals.

        In this example, the dependency between the output and one of the parent unimportant signals
        occurs across multiple cycles. Therefore, passing the important input variable as argument
        is insufficient; we instead must make the transition function for each elided state variable
        an uninterpreted function.

        Furthermore, every state variable but `b` happens to depend on an important variable, or one
        that is modeled as a UF. Accordingly, only `b` needs an extra degree of freedom argument.
        """
        rtl = textwrap.dedent("""\
            module top(input clk, input [1:0] in, input [1:0] ignore, output [1:0] out);
                reg [1:0] a;
                reg [1:0] b;
                reg [1:0] c;
                always @(posedge clk) begin
                    a <= in + 1;
                    b <= a & ignore;
                    c <= b;
                end
                assign out = c;
            endmodule
            """)
        actual_model = verilog_to_model(
            rtl,
            "top",
            important_signals=["out", "in"],
            coi_conf=COIConf.UF_ARGS_COI
        )
        actual_model.print()
        assert actual_model.validate()
        bv2 = smt.BVSort(2)
        in_ = smt.Variable("in", bv2)
        out = smt.Variable("out", bv2)
        exp_model = Model(
            "top",
            inputs=[in_],
            outputs=[out],
            next_ufs=[
                UFPlaceholder("c", bv2, (smt.Variable("b", bv2),), False),
                UFPlaceholder("b", bv2, (smt.Variable("a", bv2),), True),
                UFPlaceholder("a", bv2, (in_,), False),
            ],
            logic={out: smt.Variable("c", bv2)}
        )
        assert exp_model.validate()
        assert actual_model == exp_model

    def test_verilog_single_imp_keep_coi(self):
        """
        Tests generation of a model from a single RTL module with specified important signals.
        `coi_conf` is KEEP_COI, meaning any signal in the COI of an important signal is kept.
        """
        rtl = textwrap.dedent("""\
            module top(input clk, input should_inc, output [2:0] result);
                reg [2:0] a;
                reg [2:0] b;
                wire [2:0] a_p1;
                wire [2:0] b_p1;
                always @(posedge clk) begin
                    if (should_inc) begin
                        a = a_p1;
                        b = b_p1;
                    end
                end
                assign a_p1 = a + 3'h1;
                assign b_p1 = b + 3'h1;
                assign result = ~a | ~b;
            endmodule
            """)
        model_no_a = verilog_to_model(rtl, "top", important_signals=["b"], coi_conf=COIConf.KEEP_COI)
        model_no_b = verilog_to_model(rtl, "top", important_signals=["a"], coi_conf=COIConf.KEEP_COI)
        model_no_a.print()
        model_no_b.print()
        bv3 = smt.BVSort(3)
        var = smt.Variable
        a = var("a", bv3)
        a_p1 = var("a_p1", bv3)
        b = var("b", bv3)
        b_p1 = var("b_p1", bv3)
        should_inc = var("should_inc", smt.BoolSort())
        assert model_no_a.validate()
        assert model_no_a == Model(
            "top",
            inputs=[should_inc],
            outputs=[],
            # Even though `b_p1` isn't specified as important, it's still in the COI
            state=[b, b_p1],
            logic={b_p1: b + 1},
            default_next={b: should_inc.ite(b_p1, b)},
        )
        assert model_no_b.validate()
        assert model_no_b == Model(
            "top",
            inputs=[should_inc],
            outputs=[],
            # Even though `a_p1` isn't specified as important, it's still in the COI
            state=[a, a_p1],
            logic={a_p1: a + 1},
            default_next={a: should_inc.ite(a_p1, a)},
        )

    @pytest.mark.skip()
    def test_verilog_output_unimp(self):
        # TODO what do we do when an output is a dependency of an important signal,
        # but the output itself is non-important
        assert False

    def test_bv_int_index(self):
        """
        Tests behavior of bitvector indexing.
        This also indirectly tests behavior of bitvector width checking.
        """
        rtl = textwrap.dedent("""\
            module top(input clk, input rst, input i_inner, output o_inner);
                reg [2:0] i_state;
                always @(posedge clk) begin
                    if (rst) begin
                        i_state = 3'h0;
                    end else begin
                        i_state = i_inner | i_state;
                    end
                end
                assign o_inner = i_state[0];
            endmodule
            """
        )
        model = verilog_to_model(rtl, "top")
        model.print()
        boolsort = smt.BoolSort()
        boolvar = smt.BoolVariable
        rst = boolvar("rst")
        i_state = smt.BVVariable("i_state", 3)
        i_inner = boolvar("i_inner")
        o_inner = boolvar("o_inner")
        assert model.validate()
        assert model == Model(
            "top",
            inputs=[rst, i_inner],
            outputs=[boolvar("o_inner")],
            state=[i_state],
            default_next={
                i_state: rst.ite(
                    smt.BVConst(0, 3),
                    # The expression i_inner | i_state should implicitly upcast
                    i_inner.ite(smt.BVConst(1, 3), smt.BVConst(0, 3)) | i_state
                )
            },
            logic={o_inner: i_state[0]}
        )

    def test_verilog_bv_var_index(self):
        """
        Tests indexing a bitvector with a variable.
        """
        rtl = textwrap.dedent("""\
            module top(input clk, input bit, input [2:0] idx, output out);
                reg [7:0] op;
                always @(posedge clk) begin
                    op[idx] = bit; // Sets the idxth bit
                end
                assign out = op[idx];
            endmodule
            """)
        var = smt.Variable
        bit = var("bit", smt.BoolSort())
        idx = var("idx", smt.BVSort(3))
        out = var("out", smt.BoolSort())
        op = var("op", smt.BVSort(8))
        exp_model = Model(
            "top",
            inputs=[bit, idx],
            outputs=[out],
            state=[op],
            logic={
                # Encode extracting a bit as a shift + mask
                # because SMT extracts require constant indices
                out: smt.OpTerm(
                    smt.Kind.BVAnd,
                    (
                        smt.OpTerm(smt.Kind.BVSrl, (op, idx.zpad(5),)),
                        smt.BVConst(1, 8),
                    )
                )
            },
            default_next={
                # Encode assigning to a variable bitvector index as shift + mask
                # op[idx] = bit is equivalent to
                # op = (op & ~(1 << idx)) | (bit << idx)
                op: smt.OpTerm(
                    smt.Kind.BVOr,
                    (
                        smt.OpTerm(
                            smt.Kind.BVAnd,
                            (
                                op,
                                smt.OpTerm(
                                    smt.Kind.BVNot,
                                    (smt.OpTerm(smt.Kind.BVSll, (smt.BVConst(1, 8), idx.zpad(5))),)
                                )
                            )
                        ),
                        smt.OpTerm(smt.Kind.BVSll, (bit.zpad(7), idx.zpad(5))),
                    )
                )
            }
        )
        assert exp_model.validate()
        actual = verilog_to_model(rtl, "top")
        actual.print()
        assert actual.validate()
        assert actual == exp_model

    def test_verilog_weird_bv_assigns(self):
        """
        Tests behavior for a few different mechanisms of bitvector assignment.
        """
        rtl = textwrap.dedent("""\
            module top(input [3:0] in, output [1:0] out);
                reg [1:0] s0;
                reg [3:0] s1;
                always @(posedge clk) begin
                    s1[2] = in[2];
                    s1[1:0] = s0[1:0];
                end
                assign {{out, s0}} = in;
            endmodule
            """)
        v = smt.Variable
        in_ = v("in", smt.BVSort(4))
        out = v("out", smt.BVSort(2))
        s0 = v("s0", smt.BVSort(2))
        s1 = v("s1", smt.BVSort(4))
        exp_model = Model(
            "top",
            inputs=[in_],
            outputs=[out],
            state=[s0, s1],
            logic={
                out: in_[3:2],
                s0: in_[1:0],
            },
            default_next={
                s1[2]: in_[2],
                s1[1:0]: s0[1:0],
            }
        )
        exp_model.print()
        assert exp_model.validate()
        actual = verilog_to_model(rtl, "top")
        actual.print()
        assert actual.validate()
        assert actual == exp_model

    def test_verilog_carry_add(self):
        """
        Tests weird bitvector casting stuff that happens in a carry addition idiom.
        """
        rtl = textwrap.dedent("""\
            module top(input [3:0] a, input [3:0] b, output c, output [3:0] out);
                assign {{c, out}} = a + b;
            endmodule
            """)
        bv4 = smt.BVSort(4)
        v = smt.Variable
        a = v("a", bv4)
        b = v("b", bv4)
        c = v("c", smt.BoolSort())
        out = v("out", bv4)
        exp_model = Model(
            "top",
            inputs=[a, b],
            outputs=[c, out],
            logic={
                c: (a.zpad(1) + b.zpad(1))[4],
                out: (a + b)[3:0],
            }
        )
        assert exp_model.validate()
        actual = verilog_to_model(rtl, "top")
        actual.print()
        assert actual.validate()
        assert actual == exp_model

    def test_verilog_one_child_module(self):
        rtl = textwrap.dedent("""\
            module inner(input clk, input rst, input i_inner, output o_inner);
                reg i_state;
                always @(posedge clk) begin
                    if (rst) begin
                        i_state = 3'h0;
                    end else begin
                        i_state = i_inner | i_state;
                    end
                end
                assign o_inner = i_state;
            endmodule

            module top(input clk, input rst, input i_top, output reg o_top);
                reg i_top_last;
                wire i_out_next;
                inner sub(
                    .clk(clk),
                    .rst(rst),
                    .i_inner(i_top_last),
                    .o_inner(i_out_next)
                );
                always @(posedge clk) begin
                    i_top_last = i_top;
                    o_top = i_out_next;
                end
            endmodule
            """
        )
        # TODO specifying important_signals for children
        var = smt.Variable
        boolsort = smt.BoolSort()
        rst = var("rst", boolsort)
        i_inner = var("i_inner", boolsort)
        i_state = var("i_state", boolsort)
        i_top = var("i_top", boolsort)
        i_top_last = var("i_top_last", boolsort)
        i_out_next = var("i_out_next", boolsort)
        o_inner = var("o_inner", boolsort)
        o_top = var("o_top", boolsort)
        exp_submodel = Model(
            "inner",
            inputs=[rst, i_inner],
            outputs=[o_inner],
            state=[i_state],
            default_next={
                i_state: rst.ite(smt.BoolConst.F, i_inner | i_state)
            },
            logic={o_inner: i_state}
        )
        assert exp_submodel.validate()
        exp_top = Model(
            "top",
            inputs=[rst, i_top],
            outputs=[o_top],
            state=[i_top_last, i_out_next],
            logic={
                i_out_next: var("sub.o_inner", boolsort),
            },
            default_next={i_top_last: i_top, o_top: i_out_next},
            instances={"sub": Instance(exp_submodel, {rst: rst, i_inner: i_top_last})},
        )
        assert exp_top.validate()
        model = verilog_to_model(rtl, "top")
        model.print()
        submodel = model.instances["sub"].model
        submodel.print()
        assert submodel.validate()
        assert submodel == exp_submodel
        assert model.validate()
        assert model == exp_top

    def test_verilog_substitute_child(self):
        rtl = textwrap.dedent("""\
            module inner(input clk, input rst, input i_inner, output o_inner);
                reg i_state;
                always @(posedge clk) begin
                    if (rst) begin
                        i_state = 3'h0;
                    end else begin
                        i_state = i_inner | i_state;
                    end
                end
                assign o_inner = i_state;
            endmodule

            module top(input clk, input rst, input i_top, output reg o_top);
                reg i_top_last;
                wire i_out_next;
                inner sub(
                    .clk(clk),
                    .rst(rst),
                    .i_inner(i_top_last),
                    .o_inner(i_out_next)
                );
                always @(posedge clk) begin
                    i_top_last = i_top;
                    o_top = i_out_next;
                end
            endmodule
            """
        )
        var = smt.Variable
        boolsort = smt.BoolSort()
        rst = var("rst", boolsort)
        i_inner = var("i_inner", boolsort)
        i_top = var("i_top", boolsort)
        i_top_last = var("i_top_last", boolsort)
        i_out_next = var("i_out_next", boolsort)
        o_inner = var("o_inner", boolsort)
        o_top = var("o_top", boolsort)
        inner_def = Model(
            "inner",
            inputs=[rst, i_inner],
            outputs=[o_inner],
            logic={o_inner: smt.BoolConst.F},
        )
        assert inner_def.validate()
        exp_top = Model(
            "top",
            inputs=[rst, i_top],
            outputs=[o_top],
            state=[i_top_last, i_out_next],
            logic={
                i_out_next: var("sub.o_inner", boolsort),
            },
            default_next={i_top_last: i_top, o_top: i_out_next},
            instances={"sub": Instance(inner_def, {rst: rst, i_inner: i_top_last})},
        )
        assert exp_top.validate()
        model = verilog_to_model(rtl, "top", defined_modules=[inner_def])
        model.print()
        submodel = model.instances["sub"].model
        assert submodel == inner_def
        assert model.validate()
        assert model == exp_top

    def test_verilog_array(self):
        """
        Tests parsing of verilog arrays.
        """
        rtl = textwrap.dedent("""
            module top(
                input clk,
                input wen,
                input [1:0] ra,
                input [3:0] wdata,
                output [3:0] rdata
            );
                reg [3:0] arr [0:2]; // 3 4-bit elements, indexed 0 through 2
                always @(posedge clk) begin
                    if (wen) begin
                        arr[ra] <= wdata;
                    end
                end
                assign rdata = arr[ra];
            endmodule
            """)
        model = verilog_to_model(rtl, "top")
        model.print()
        wdata = smt.Variable("wdata", smt.BVSort(4))
        wen = smt.Variable("wen", smt.BoolSort())
        reg = smt.Variable("ra", smt.BVSort(2))
        arr = smt.Variable("arr", smt.ArraySort(smt.BVSort(2), smt.BVSort(4)))
        rdata = smt.Variable("rdata", smt.BVSort(4))
        assert model.validate()
        assert model == Model(
            "top",
            inputs=[wen, reg, wdata],
            outputs=[rdata],
            state=[arr],
            logic={rdata: arr[reg]},
            default_next={arr[reg]: wen.ite(wdata, arr[reg])},
        )

    def test_verilog_nested_child_no_coi(self):
        """
        Tests behavior for when a child module itself has another child module.

        Note also that there are many shared signal names.
        """
        rtl = textwrap.dedent("""
            module inner2(input clk, input [3:0] value, output [3:0] o);
                reg [3:0] state;
                always @(posedge clk) begin
                    state = value + 4'h1;
                end
                assign o = state ^ 4'b1111;
            endmodule

            module inner1(input clk, input [3:0] value, output [3:0] o);
                reg [3:0] state;
                wire [3:0] inner_s;
                inner2 inst(
                    .value(value),
                    .o(inner_s)
                );
                always @(posedge clk) begin
                    state = inner_s ^ value;
                end
                assign o = state | 4'b110;
            endmodule

            module top(input clk, input [3:0] value, output [3:0] o);
                reg [3:0] state;
                wire [3:0] inner_s;
                inner1 inst(
                    .value(state),
                    .o(inner_s)
                );
                always @(posedge clk) begin
                    state = inner_s & value;
                end
                assign o = inner_s;
            endmodule
            """)
        bvar = smt.BVVariable
        value = bvar("value", 4)
        o = bvar("o", 4)
        state = bvar("state", 4)
        inner_s = bvar("inner_s", 4)
        exp_inner2 = Model(
            "inner2",
            inputs=[value],
            outputs=[o],
            state=[state],
            logic={o: state ^ smt.BVConst(0b1111, 4)},
            default_next={state: value + 1},
        )
        exp_inner1 = Model(
            "inner1",
            inputs=[value],
            outputs=[o],
            state=[state, inner_s],
            instances={"inst": Instance(exp_inner2, {value: value})},
            logic={inner_s: bvar("inst.o", 4), o: state | smt.BVConst(0b0110, 4)},
            default_next={state: inner_s ^ value},
        )
        exp_top = Model(
            "top",
            inputs=[value],
            outputs=[o],
            state=[state, inner_s],
            instances={"inst": Instance(exp_inner1, {value: state})},
            logic={inner_s: bvar("inst.o", 4), o: inner_s},
            default_next={state: inner_s & value}
        )
        assert exp_inner2.validate()
        assert exp_inner1.validate()
        assert exp_top.validate()
        top = verilog_to_model(rtl, "top")
        top.print()
        inner1 = top.instances["inst"].model
        inner1.print()
        inner2 = inner1.instances["inst"].model
        inner2.print()
        assert inner2.validate()
        assert inner1.validate()
        assert top.validate()
        assert inner2 == exp_inner2
        assert inner1 == exp_inner1
        assert top == exp_top

    @pytest.mark.skip()
    def test_verilog_nested_child_coi(self):
        """
        Tests behavior when COI options are enabled and child submodules are traversed.
        """
        ...
        assert False

    @pytest.mark.skip()
    def test_verilog_reused_child(self):
        """
        Tests when a module has multiple instances within a design.
        """
        # Note: in our case studies, rvmini reuses a module just once (the cache)
        ...
        assert False
