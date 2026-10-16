"""Scientific validity guards for the paper benchmark, using synthetic data only."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

SPEC=importlib.util.spec_from_file_location('benchmark',Path(__file__).resolve().parents[1]/'tools/paper/benchmark.py')
b=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(b)


def row(label, h=30, y=2e9):
    r={f:'' for f in b.FEATURES}
    r.update(sample_label=label,group_id=label,device_type='MINION_MK1D',horizon_minutes=str(h),target_final_passed_bases=str(y),observed_through_seconds=str(h*60),observed_passed_bases='1000000000',planned_run_limit_hours='24',observed_recent_passed_bases_per_hour='2000000000')
    return r


class BenchmarkTests(unittest.TestCase):
    def test_group_partitions_disjoint_and_each_tested_once(self):
        rows=[row(str(i),h) for i in range(30) for h in (30,60,120)]
        splits=b.exploratory_splits(rows,5,3)
        seen=[]
        for split in splits:
            self.assertFalse(split['train']&split['test'])
            self.assertFalse(split['calibration']&split['test'])
            self.assertFalse(split['calibration']&split['train'])
            seen.extend(split['test'])
        self.assertEqual(len(seen),len(set(seen)))
        self.assertEqual(set(seen),{r['group_id'] for r in rows})
        self.assertEqual(splits,b.exploratory_splits(rows,5,3))

    def test_conformal_finite_sample_correction(self):
        self.assertTrue(np.isinf(b.conformal_radius([1,2,3],95)))
        self.assertEqual(b.conformal_radius(list(range(20)),90),18)
        self.assertEqual(b.conformal_radius(list(range(20)),95),19)

    def test_related_group_max_scores(self):
        rows=[row('a',y=0),row('b',y=1e9),row('c',y=2e9)]
        rows[1]['group_id']='a'
        scores,signed=b.calibrate(rows,np.zeros(3))
        np.testing.assert_allclose(sorted(scores),[np.log(2),np.log(3)])
        self.assertAlmostEqual(sum(w for _,w in signed),2)

    def test_extrapolation_uses_planned_not_actual_duration(self):
        r=row('a'); r['actual_duration_hours']='9999'
        self.assertEqual(b.baseline([r],'linear_planned')[0],48)
        r['planned_run_limit_hours']=''
        self.assertTrue(np.isnan(b.baseline([r],'linear_planned')[0]))
        r['planned_run_limit_hours']='0.1'
        self.assertTrue(np.isnan(b.baseline([r],'linear_planned')[0]))

    def test_preprocessing_fits_only_training_rows(self):
        train=[row(str(i),y=(i+1)*1e9) for i in range(4)]
        cal=[row('cal')]; test=[row('test')]
        cal[0]['observed_passed_bases']='900000000000'
        test[0]['observed_passed_bases']='800000000000'
        original=b.SimpleImputer.fit
        fitted=[]
        def inspect(instance,X,*args,**kwargs):
            fitted.append(X.copy()); return original(instance,X,*args,**kwargs)
        with patch.object(b.SimpleImputer,'fit',inspect):
            b.fit_predict(train,cal,test,'ridge',1)
        self.assertEqual(len(fitted),1)
        np.testing.assert_equal(fitted[0],b.matrix(train))

    def test_relabelled_replay_cannot_be_a_reserved_cohort(self):
        rows=b.read_data(b.REPLAY)[:3]
        for r in rows: r['sample_label']='renamed'
        with self.assertRaisesRegex(ValueError,'development evidence'):
            b.reject_development_overlap(list(reversed(rows)))

    def test_invalid_input_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'rows.csv'
            r=row('a'); r['observed_through_seconds']='1801'
            b.write_csv(p,[r])
            with self.assertRaisesRegex(ValueError,'Observation time'):
                b.read_data(p)
            r=row('a'); b.write_csv(p,[r,r])
            with self.assertRaisesRegex(ValueError,'unique'):
                b.read_data(p)

    def test_manifest_rejects_leakage_and_unverified_timing(self):
        rows=[row(x) for x in ('a','b','c')]
        records=[dict(sample_label=x,group_id=x,partition=p,run_start_utc=f'2026-01-0{i}T00:00:00Z',outcome_available_utc=f'2026-01-0{i}T01:00:00Z',timing_verified='true') for i,(x,p) in enumerate(zip(('a','b','c'),('train','calibration','test')),1)]
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'split.csv'; b.write_csv(p,records)
            self.assertEqual(b.manifest_split(rows,p)[0]['test'],{'c'})
            records[2]['group_id']='a'; b.write_csv(p,records)
            with self.assertRaisesRegex(ValueError,'overlap'):
                b.manifest_split(rows,p)
            records[2]['group_id']='c'; records[0]['outcome_available_utc']='2026-01-04T00:00:00Z'; b.write_csv(p,records)
            with self.assertRaisesRegex(ValueError,'Chronology'):
                b.manifest_split(rows,p)
            records[0]['timing_verified']='false'; b.write_csv(p,records)
            with self.assertRaisesRegex(ValueError,'timing_verified'):
                b.manifest_split(rows,p)

    def test_common_denominator_and_metrics(self):
        preds=[]
        for m in b.METHODS:
            for i in range(2):
                r=dict(fold=0,sample_label=str(i),group_id=str(i),horizon_minutes=30,method=m,actual_gb=1.,prediction_gb=2. if i==0 else 3.)
                for c in b.COVERAGES:
                    r[f'lower_{c}']=0.; r[f'upper_{c}']=4.
                if m=='recent_planned' and i==1: r['prediction_gb']=np.nan
                preds.append(r)
        stats=b.summarize(preds,[],1,bootstrap=10)
        selected=[r for r in stats if r['horizon_minutes']==30 and r['scope']=='common']
        self.assertTrue(all(r['n_predicted']==1 and r['mae_gb']==1 for r in selected))
        self.assertTrue(all(r['coverage_90']==1 for r in selected))


if __name__=='__main__': unittest.main()
