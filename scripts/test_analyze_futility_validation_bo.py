import copy
import importlib.util
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))

@unittest.skipUnless(importlib.util.find_spec('tinibo'),'requires tinibo')
class ValidationBOTest(unittest.TestCase):
    def test_full_population_and_conflicts(self):
        import analyze_futility_validation_bo as study
        rows={}
        item=dict(margins=[0,40,158,488,754],metrics=dict(evaluated_positions=141099,mean_normalized_regret=.014))
        study.add_rows(rows,[item,item])
        self.assertEqual(len(rows),1)
        changed=copy.deepcopy(item)
        changed['metrics']['mean_normalized_regret']=.02
        with self.assertRaisesRegex(ValueError,'conflicting'): study.add_rows(rows,[changed])
        changed['metrics']['evaluated_positions']=22825
        with self.assertRaisesRegex(ValueError,'complete pooled'): study.add_rows(rows,[changed])

    def test_cross_validation_and_unvalidated_pool(self):
        import analyze_futility_validation_bo as study
        rows=[dict(margins=[i,i+10,i+30,i+100,i+200],target=.02+i*.0001) for i in range(12)]
        pool=[r['margins'] for r in rows]+[[20,30,50,120,220],[30,40,60,130,230]]
        result=study.study(rows,pool,restarts=1,iterations=3)
        self.assertEqual(result['training_count'],12)
        measured={tuple(r['margins']) for r in rows}
        for row in result['proposals']: self.assertNotIn(tuple(row['margins']),measured)
        for check in result['prediction_checks']:
            tests=[]
            for fold in check['folds']:
                self.assertFalse(set(fold['train']) & set(fold['test']))
                tests.extend(fold['test'])
            self.assertEqual(sorted(tests),list(range(12)))
