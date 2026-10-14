import unittest
from ai_novel_factory.scene_vectors import SceneVector, search_scenes, pgvector_search, PGVECTOR_SCHEMA
from ai_novel_factory.planning import PlanningError

class Stage56Tests(unittest.TestCase):
    def setUp(self):
        self.scenes=(SceneVector('A',1,1,(1.,0.,0.),'one'),SceneVector('A',2,1,(0.,1.,0.),'two'),SceneVector('B',1,1,(1.,0.,0.),'secret'),SceneVector('A',3,1,(1.,0.,0.),'future'))
    def test_ranking(self):
        self.assertEqual([h.summary for h in search_scenes('A',3,(1.,0.,0.),self.scenes)],['one','two'])
    def test_isolation(self):
        self.assertNotIn('secret',[h.summary for h in search_scenes('A',3,(1.,0.,0.),self.scenes)])
    def test_future_excluded(self):
        self.assertNotIn('future',[h.summary for h in search_scenes('A',3,(1.,0.,0.),self.scenes)])
    def test_empty(self):
        self.assertEqual(search_scenes('A',1,(1.,0.,0.),self.scenes),())
    def test_zero(self):
        with self.assertRaises(PlanningError): search_scenes('A',3,(0.,0.,0.),self.scenes)
    def test_nan(self):
        with self.assertRaises(PlanningError): search_scenes('A',3,(float('nan'),0.,0.),self.scenes)
    def test_dimension(self):
        with self.assertRaises(PlanningError): search_scenes('A',3,(1.,0.),self.scenes)
    def test_duplicate(self):
        with self.assertRaises(PlanningError): search_scenes('A',3,(1.,0.,0.),self.scenes+self.scenes[:1])
    def test_limit(self):
        self.assertEqual(len(search_scenes('A',3,(1.,0.,0.),self.scenes,limit=1)),1)
    def test_bad_limit(self):
        with self.assertRaises(PlanningError): search_scenes('A',3,(1.,0.,0.),self.scenes,limit=0)
    def test_pgvector_sql_parameters(self):
        class Cursor:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def execute(self,sql,args):
                self.sql=sql; self.args=args
                assert 'project_id = %s' in sql and 'episode_number < %s' in sql
                assert args[1:3]==('A',3)
            def fetchall(self): return [(1,1,'one',0.9)]
        class Connection:
            def cursor(self): return Cursor()
        self.assertEqual(pgvector_search(Connection(),'A',3,(1.,0.,0.))[0].summary,'one')
    def test_pgvector_rejects_future_result(self):
        class Cursor:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def execute(self,*args): pass
            def fetchall(self): return [(3,1,'bad',0.9)]
        class Connection:
            def cursor(self): return Cursor()
        with self.assertRaises(PlanningError): pgvector_search(Connection(),'A',3,(1.,0.,0.))
    def test_schema(self):
        self.assertIn('vector(3)',PGVECTOR_SCHEMA)
if __name__=='__main__': unittest.main()
