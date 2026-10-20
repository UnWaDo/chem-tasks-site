import unittest

from chem.equation import EquationError, markup_html, parse_equation
from chem.formula import FormulaError, formula_html, parse_formula
from chem.grading import grade


class FormulaTests(unittest.TestCase):
    def test_atoms(self):
        self.assertEqual(parse_formula("K4[Fe(CN)6]").atoms, {"K": 4, "Fe": 1, "C": 6, "N": 6})
        self.assertEqual(parse_formula("(NH4)2SO4").atoms, {"N": 2, "H": 8, "S": 1, "O": 4})
        self.assertEqual(parse_formula("CuSO4·5H2O").atoms, {"Cu": 1, "S": 1, "O": 9, "H": 10})
        self.assertEqual(parse_formula("CuSO4*5H2O").text, "CuSO4·5H2O")
        self.assertEqual(parse_formula("CuSO4.5H2O").text, "CuSO4·5H2O")
        self.assertEqual(parse_formula("H₂O").text, "H2O")
        self.assertEqual(parse_formula("Co").atoms, {"Co": 1})
        self.assertEqual(parse_formula("CO").atoms, {"C": 1, "O": 1})

    def test_charges(self):
        cases = {
            "SO4^2-": ("SO4^2-", -2), "SO4{2-}": ("SO4^2-", -2), "SO4^{2-}": ("SO4^2-", -2),
            "SO₄²⁻": ("SO4^2-", -2), "SO42-": ("SO4^2-", -2), "NH4+": ("NH4^+", 1),
            "Fe3+": ("Fe^3+", 3), "Fe^3+": ("Fe^3+", 3), "Cr2O72-": ("Cr2O7^2-", -2),
            "OH-": ("OH^-", -1), "H+": ("H^+", 1), "e": ("e^-", -1), "ē": ("e^-", -1),
            "S2-": ("S^2-", -2),
        }
        for raw, (text, charge) in cases.items():
            f = parse_formula(raw)
            self.assertEqual((f.text, f.charge), (text, charge), raw)

    def test_errors(self):
        for bad in ["", "Xx", "h2o", "Fe(OH", "Fe)", "()"]:
            with self.assertRaises(FormulaError, msg=bad):
                parse_formula(bad)

    def test_html(self):
        self.assertEqual(formula_html("CuSO4·5H2O"), "CuSO<sub>4</sub>·5H<sub>2</sub>O")
        self.assertEqual(formula_html("SO4^2-"), "SO<sub>4</sub><sup>2−</sup>")


class EquationTests(unittest.TestCase):
    def test_basic(self):
        eq = parse_equation("2H2 + O2 = 2H2O")
        self.assertEqual([t.coef for t in eq.terms], [2, None, 2])
        self.assertTrue(eq.analyze().ok)

    def test_conditions_and_notes(self):
        eq = parse_equation("2KClO3 =^(t)_(MnO2) 2KCl + 3O2↑")
        self.assertEqual((eq.above, eq.below), ("t", "MnO2"))
        self.assertEqual(eq.right[1].mark, "↑")
        eq = parse_equation("Cu + 4HNO3(конц.) → Cu(NO3)2 + 2NO2 + 2H2O")
        self.assertEqual(eq.left[1].note, "конц.")
        self.assertEqual(eq.right[0].formula.text, "Cu(NO3)2")
        eq = parse_equation("NH3 + H2SO4 = (NH4)2SO4")
        self.assertEqual(eq.above, "")
        self.assertEqual(eq.right[0].formula.text, "(NH4)2SO4")
        eq = parse_equation("2NH3 + H2SO4 =(t) (NH4)2SO4")
        self.assertEqual(eq.above, "t")
        eq = parse_equation("Fe(OH)3(тв) =(t) Fe2O3 + H2O(г)")
        self.assertEqual((eq.left[0].formula.text, eq.left[0].note), ("Fe(OH)3", "тв"))

    def test_ions(self):
        eq = parse_equation("Fe3+ + 3OH- = Fe(OH)3↓")
        self.assertEqual([t.formula.text for t in eq.left], ["Fe^3+", "OH^-"])
        self.assertTrue(eq.analyze().balanced)
        eq = parse_equation("Cu2+ + 2e = Cu")
        self.assertTrue(eq.analyze().balanced)
        self.assertFalse(parse_equation("Cu2+ + e = Cu").analyze().balanced)

    def test_balance_suggestions(self):
        a = parse_equation("Al + O2 = Al2O3").analyze()
        self.assertFalse(a.balanced)
        self.assertEqual(a.options, [[4, 3, 2]])
        a = parse_equation("C3H8 + O2 → CO2 + H2O").analyze()
        self.assertEqual(a.options, [[1, 5, 3, 4]])
        a = parse_equation("4H2 + 2O2 = 4H2O").analyze()
        self.assertTrue(a.reducible)
        self.assertEqual(a.options, [[2, 1, 2]])
        a = parse_equation("KMnO4 + H2O2 + H2SO4 = K2SO4 + MnSO4 + O2 + H2O").analyze()
        self.assertTrue(a.ambiguous)
        self.assertIn([2, 5, 3, 1, 2, 5, 8], a.options + [[2, 5, 3, 1, 2, 5, 8]])
        self.assertTrue(parse_equation("Na + Cl2 = KCl").analyze().impossible)

    def test_signature(self):
        a = parse_equation("NaOH + HCl = NaCl + H2O").signature()
        b = parse_equation("HCl + NaOH → H2O + NaCl").signature()
        c = parse_equation("HCl + NaOH →(t) H2O + NaCl").signature()
        d = parse_equation("HCl(конц) + NaOH → H2O + NaCl").signature()
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertNotEqual(a, d)

    def test_errors(self):
        for bad in ["H2 + O2", "H2 = O2 = H2O", "H2 + + O2 = H2O", "1/2O2 + H2 = H2O"]:
            with self.assertRaises(EquationError, msg=bad):
                parse_equation(bad)


class MarkupTests(unittest.TestCase):
    def test_markup(self):
        self.assertEqual(markup_html("HCl_((aq.))"), "HCl<sub>(aq.)</sub>")
        self.assertEqual(markup_html("Fe^(3+)"), "Fe<sup>3+</sup>")
        self.assertEqual(markup_html("x^2"), "x<sup>2</sup>")
        self.assertEqual(markup_html("a_(b_(c))"), "a<sub>b<sub>c</sub></sub>")
        self.assertEqual(markup_html("500 <b>"), "500 &lt;b&gt;")
        self.assertEqual(markup_html("x_"), "x_")

    def test_degree_sign(self):
        for raw in ["t°", "t^o", "t^(o)", "t^\\circ", "t^(\\circ)", "t\\circ", "t^о", "t^ (o)"]:
            self.assertEqual(markup_html(raw), "t°", raw)
        self.assertEqual(markup_html("500^oC, cat"), "500°C, cat")
        self.assertEqual(markup_html("x^ox"), "x<sup>ox</sup>")   # не градус
        a = parse_equation("2H2 + O2 =^(t°) 2H2O").signature()
        b = parse_equation("2H2 + O2 =^(t^\\circ) 2H2O").signature()
        c = parse_equation("2H2 + O2 =^(t^(o)) 2H2O").signature()
        self.assertEqual(a, b)
        self.assertEqual(a, c)

    def test_conditions_with_markup(self):
        eq = parse_equation("Zn + 2HCl →_(HCl_((aq.))) ZnCl2 + H2↑")
        self.assertEqual(eq.below, "HCl_((aq.))")
        self.assertIn("<sub>(aq.)</sub>", markup_html(eq.below))


class GradingTests(unittest.TestCase):
    ref = [({"H2": 2, "O2": 1}, {"H2O": 2})]

    def test_grades(self):
        g = grade({"L": [{"c": "2", "f": "H2"}, {"c": "", "f": "O2"}], "R": [{"c": "2", "f": "H₂O"}]}, self.ref)
        self.assertEqual(g.verdict, "correct")
        g = grade({"L": [{"c": "4", "f": "H2"}, {"c": "2", "f": "O2"}], "R": [{"c": "4", "f": "H2O"}]}, self.ref)
        self.assertEqual((g.verdict, g.score), ("partial", 0.5))
        g = grade({"L": [{"c": "1", "f": "H2"}, {"c": "1", "f": "O2"}], "R": [{"c": "1", "f": "H2O"}]}, self.ref, 0)
        self.assertEqual((g.verdict, g.score), ("partial", 0))
        g = grade({"L": [{"f": "H2"}], "R": [{"f": "H2O"}]}, self.ref)
        self.assertEqual(g.verdict, "wrong")
        g = grade({"L": [], "R": []}, self.ref)
        self.assertEqual(g.verdict, "empty")

    def test_water(self):
        ref = [({"NaOH": 1, "HCl": 1}, {"NaCl": 1, "H2O": 1})]
        g = grade({"L": [{"f": "NaOH"}, {"f": "HCl"}, {"f": "H2O"}], "R": [{"f": "NaCl"}]}, ref)
        self.assertIn("вод", g.feedback)


if __name__ == "__main__":
    unittest.main()
