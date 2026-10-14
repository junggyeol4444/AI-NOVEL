import unittest
from ai_novel_factory.database.episodes import EpisodeStore, EpisodeError
from ai_novel_factory.database.novel_bible import NovelBibleError
from ai_novel_factory.episode_retrieval import search_episode_history

class Stage57Tests(unittest.TestCase):
    def setUp(self):
        self.store = EpisodeStore(':memory:')
        self.a = self.store.create_project('Alpha').project_id
        self.b = self.store.create_project('Beta').project_id
        for project, number, summary, draft in ((self.a,1,'비밀 단서 발견','과거 원고 키워드'),(self.a,2,'단서 추적','초고'),(self.a,3,'미래 단서','초고'),(self.b,1,'비밀 단서','다른 작품')):
            ep=self.store.create_episode(project,number)
            self.store.update_episode(project,number,expected_revision=ep.revision,summary=summary,draft=draft)
    def tearDown(self): self.store.close()
    def test_summary(self): self.assertEqual([h.episode for h in search_episode_history(self.store,self.a,3,'단서')],[2,1])
    def test_no_future(self): self.assertEqual(search_episode_history(self.store,self.a,2,'추적'),())
    def test_isolation(self): self.assertEqual(len(search_episode_history(self.store,self.a,3,'비밀')),1)
    def test_manuscript_opt_in(self):
        self.assertEqual(search_episode_history(self.store,self.a,3,'키워드'),())
        self.assertEqual(search_episode_history(self.store,self.a,3,'키워드',include_manuscript=True)[0].field,'draft')
    def test_casefold(self):
        ep=self.store.get_episode(self.a,1)
        self.store.update_episode(self.a,1,expected_revision=ep.revision,summary='Hello WORLD')
        self.assertEqual(len(search_episode_history(self.store,self.a,3,'world')),1)
    def test_limit(self): self.assertEqual(len(search_episode_history(self.store,self.a,3,'단서',limit=1)),1)
    def test_empty_query(self):
        with self.assertRaises(EpisodeError): search_episode_history(self.store,self.a,3,' ')
    def test_bad_options(self):
        for kwargs in ({'limit':0},{'include_manuscript':1},{'excerpt_chars':2}):
            with self.assertRaises(EpisodeError): search_episode_history(self.store,self.a,3,'단서',**kwargs)
    def test_bad_episode(self):
        with self.assertRaises(EpisodeError): search_episode_history(self.store,self.a,True,'단서')
    def test_missing_project(self):
        with self.assertRaises(NovelBibleError): search_episode_history(self.store,'0'*32,3,'단서')
    def test_excerpt_bounded(self):
        self.assertTrue(all(len(h.excerpt)<=20 for h in search_episode_history(self.store,self.a,3,'단서',excerpt_chars=20)))

if __name__=='__main__': unittest.main()
