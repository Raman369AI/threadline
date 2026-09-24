import tempfile
import unittest
from pathlib import Path

from threadline.service import SnapshotStore, ThreadlineError


class RelatedTestsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        (root/'app').mkdir();(root/'tests').mkdir();(root/'app'/'__init__.py').write_text('')
        (root/'app'/'orders.py').write_text("""from fastapi import APIRouter
router = APIRouter(prefix="/orders")
def validate(order):
    return bool(order)
def place_order(order):
    if validate(order):
        return save(order)
def save(order):
    return order
def unrelated():
    pass
@router.get("/{order_id}")
def read_order(order_id: int):
    return {"id": order_id}
""")
        (root/'tests'/'test_orders.py').write_text("""from app.orders import place_order, validate
def make():
    return place_order({"x": 1})
def test_place_order_saves():
    assert place_order({"x": 1})
def test_helper_path():
    assert make()
def test_validate_rejects_empty():
    assert not validate({})
def test_read_order(client):
    client.get("/orders/42?full=1")
class TestSave:
    def test_save_roundtrip(self):
        pass
""")
        self.store=SnapshotStore(root)
        self.ids={scope['qualified']:sid for sid,scope in self.store.current['scopes'].items()}

    def related(self, name):
        result=self.store.related_tests(self.ids[name])
        return result, [(row['name'],row['relation'],row['status']) for row in result['items']['items']]

    def test_direct_callers_rank_before_helper_chains(self):
        result, rows=self.related('validate')
        self.assertEqual(result['role'],'code')
        self.assertEqual(rows,[('test_validate_rejects_empty','direct','supported'),
                               ('test_place_order_saves','indirect','supported'),
                               ('test_helper_path','indirect','supported')])
        chain=result['items']['items'][2]
        self.assertEqual(chain['via'],['make','place_order'])
        self.assertIn('evidenceId',chain)

    def test_route_requests_and_names_are_possible_links(self):
        self.assertEqual(self.related('read_order')[1],[('test_read_order','route','possible')])
        self.assertIn(('TestSave.test_save_roundtrip','name','possible'),self.related('save')[1])
        self.assertEqual(self.related('unrelated')[1],[])

    def test_selected_test_lists_the_code_it_exercises_through_helpers(self):
        result=self.store.related_tests(self.ids['test_helper_path'])
        self.assertEqual(result['role'],'test')
        self.assertEqual([(row['name'],row['via']) for row in result['items']['items']],[('place_order',['make'])])

    def test_unknown_symbols_and_pages_are_rejected(self):
        with self.assertRaises(ThreadlineError): self.store.related_tests('missing')
        with self.assertRaises(ThreadlineError): self.store.related_tests(self.ids['save'],limit=0)


if __name__=='__main__':
    unittest.main()
