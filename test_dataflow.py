import json
import tempfile
import unittest
from pathlib import Path

from threadline.analyzer import analyze
from threadline.dataflow import build_dataflow
from threadline.templates import attach_template_assets


FIXTURE = Path(__file__).parent / 'tests' / 'fixtures' / 'dataflow_dashboard.py'


class DataflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'dashboard.py').write_text(FIXTURE.read_text())
        templates = self.root / 'templates'
        templates.mkdir()
        (templates / 'dashboard.html').write_text('''
<h1>{{ stats.total_projects }}</h1>
{% for project in recent_projects %}
<p>{{ project.task_count }}</p>
{% endfor %}
<script>apiFetch('/agents/usage')</script>
''')
        self.model = analyze(self.root)
        attach_template_assets(self.model, self.root)

    def flow(self, name, **options):
        scope = next(scope for scope in self.model['scopes'].values() if scope['name'] == name)
        return build_dataflow(self.model, scope['id'], **options)

    def test_alias_rebind_mutation_key_add_delete_and_return(self):
        flow = self.flow('edit_values')
        events = flow['events']
        self.assertIn('reassigned_name', [event['kind'] for event in events])
        self.assertIn('added_item', [event['kind'] for event in events])
        self.assertIn('added_key', [event['kind'] for event in events])
        self.assertIn('removed_key', [event['kind'] for event in events])
        self.assertIn('return', [event['kind'] for event in events])
        names = {node['name']: node for node in flow['nodes'] if node['kind'] == 'local'}
        self.assertEqual(names['original']['objectId'], next(node['objectId'] for node in flow['nodes'] if node['name'] == 'items' and node['kind'] == 'parameter'))
        self.assertNotEqual(names['original']['objectId'], names['items']['objectId'])
        self.assertNotEqual(names['original']['objectId'], names['copied']['objectId'])
        self.assertNotIn('objectId', names['unknown'])
        returned = next(node for node in flow['nodes'] if node['kind'] == 'output')
        traced = self.flow('edit_values', node_id=returned['id'], direction='upstream')['trace']
        traced_kinds = {event['kind'] for event in events if event['id'] in traced['eventIds']}
        self.assertIn('added_key', traced_kinds)
        self.assertIn('removed_key', traced_kinds)
        self.assertIn('added_item', traced_kinds)
        self.assertTrue(all(row['span']['hash'] == self.model['files']['dashboard.py']['hash']
                            for row in events))
        json.dumps(flow)

    def test_branch_retains_multiple_possible_origins(self):
        flow = self.flow('branch')
        joins = [event for event in flow['events'] if event['kind'] == 'join'
                 and 'result' in event['label']]
        self.assertEqual(len(joins), 1)
        self.assertGreaterEqual(len(joins[0]['inputs']), 2)
        self.assertEqual(joins[0]['certainty'], 'possible')
        self.assertEqual(joins[0]['span']['start'], 1 + FIXTURE.read_text()[:FIXTURE.read_text().index('    if enabled:')].count('\n'))

    def test_conditional_expression_effects_are_guarded_and_generator_deferred(self):
        flow = self.flow('expression_paths')
        appends = [row for row in flow['events'] if row['kind'] == 'added_item']
        self.assertEqual(len(appends), 2)
        self.assertEqual(appends[0]['guards'][0]['branch'], 'true')
        self.assertEqual(appends[1]['guards'][0]['kind'], 'short-circuit')
        self.assertTrue(any(row['kind'] == 'join' and row['certainty'] == 'possible'
                            for row in flow['events']))
        self.assertTrue(any(row['kind'] == 'deferred_generator' and row['details']['bodyDeferred']
                            for row in flow['events']))
        self.assertFalse(any(row['kind'] == 'call' and 'transform' in row['label']
                             for row in flow['events']))

    def test_dashboard_models_context_and_template_boundary(self):
        flow = self.flow('dashboard')
        models = {row['name']: row for row in flow['models']}
        self.assertEqual(models['Project']['status'], 'indexed')
        self.assertFalse(any(row['name'] in ('Task.id', 'AgentSession.task_id.is_not')
                             for row in flow['models']))
        self.assertIn('description', [field['name'] for field in models['Project']['fields']])
        inherited = next(field for field in models['Project']['fields']
                         if field['name'] == 'tenant_id')
        self.assertEqual(inherited['owner'], 'BaseProject')
        self.assertIn('label', [field['name'] for field in models['Task']['fields']])
        self.assertNotIn('task_count', [field['name'] for field in models['Project']['fields']])
        dependency = next(node for node in flow['nodes'] if node['kind'] == 'parameter'
                          and node['name'] == 'db')
        self.assertEqual(dependency['inputKind'], 'framework_dependency')
        self.assertEqual(dependency['declaredProvider'], 'get_db')
        self.assertTrue(any(event['kind'] == 'assigned_field' and 'project.task_count' in event['label']
                            for event in flow['events']))
        self.assertTrue(any(event['kind'] == 'template_context' and event['details']['key'] == 'recent_projects'
                            for event in flow['events']))
        self.assertFalse(any(event['kind'] == 'template_context' and event['details']['key'] == 'x-test'
                             for event in flow['events']))
        queries = [event['details']['queryShape'] for event in flow['events']
                   if event['kind'] == 'call' and 'queryShape' in event['details']]
        self.assertIn('Task', queries)
        self.assertGreaterEqual(queries.count('func.count(Task.id)'), 3)
        self.assertGreaterEqual(queries.count('Task'), 2)
        self.assertIn('AgentApproval', queries)
        self.assertIn('AgentSession', queries)
        names = {node['name'] for node in flow['nodes']}
        self.assertTrue({'visible_ids', 'task_rows', 'tasks_by_id', 'approval_rows',
                         'session_rows', 'latest_sessions'} <= names)
        self.assertTrue(any(row['kind'] == 'call' and 'latest_sessions.setdefault' in row['label']
                            for row in flow['events']))
        self.assertTrue(any(row['kind'] == 'updated_object' and 'setdefault' in row['label']
                            for row in flow['events']))
        attention_appends = [event for event in flow['events'] if event['kind'] == 'added_item'
                             and 'attention' in event['label']]
        self.assertEqual(len(attention_appends), 3)
        self.assertTrue(all(event['guards'] for event in attention_appends))
        self.assertEqual(len({event['guards'][-1]['condition'] for event in attention_appends}), 3)
        template = flow['templates'][0]
        self.assertEqual(template['status'], 'matched')
        self.assertIn('/agents/usage', [row['path'] for row in template['clientFetches']])
        task_count_use = next(row for row in template['uses'] if row['expression'] == 'project.task_count')
        self.assertTrue(task_count_use['sourceNodes'])
        template_event = next(row for row in flow['events'] if row['kind'] == 'template_use'
                              and 'project.task_count' in row['label'])
        self.assertTrue(template_event['span']['file'].endswith('dashboard.html'))
        field = next(row for row in flow['nodes'] if row['kind'] == 'field'
                     and row['name'] == 'project.task_count')
        self.assertIn(field['id'], template_event['inputs'])
        traced = self.flow('dashboard', node_id=field['id'], direction='downstream')['trace']
        self.assertIn(template_event['id'], traced['eventIds'])
        self.assertTrue(any(row['kind'] == 'opaque_call_result' for row in flow['gaps']))
        json.dumps(flow)

    def test_literal_dict_keys_reach_only_matching_template_uses(self):
        (self.root / 'keys.py').write_text('''
from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory='templates')

def keys(request, x, y):
    stats = {'a': x, 'b': y}
    return templates.TemplateResponse(request, 'keys.html',
                                      {'stats': stats, 'other': x})
''')
        (self.root / 'templates' / 'keys.html').write_text(
            '{{ stats.a }} {{ stats["b"] }} {{ other }}')
        model = analyze(self.root)
        attach_template_assets(model, self.root)
        scope = next(row for row in model['scopes'].values()
                     if row['file'] == 'keys.py' and row['name'] == 'keys')
        flow = build_dataflow(model, scope['id'])
        nodes = flow['nodes']
        uses = {row['label'].removeprefix('template uses '): row for row in flow['events']
                if row['kind'] == 'template_use'}
        self.assertEqual({'stats.a', 'stats["b"]', 'other'}, set(uses))
        key_a = next(row for row in nodes if row['name'] == "stats['a']")
        key_b = next(row for row in nodes if row['name'] == "stats['b']")
        self.assertIn(key_a['id'], uses['stats.a']['inputs'])
        self.assertNotIn(key_b['id'], uses['stats.a']['inputs'])
        self.assertIn(key_b['id'], uses['stats["b"]']['inputs'])
        self.assertNotIn(key_a['id'], uses['stats["b"]']['inputs'])
        trace_a = build_dataflow(model, scope['id'], node_id=key_a['id'],
                                 direction='downstream')['trace']
        self.assertIn(uses['stats.a']['id'], trace_a['eventIds'])
        self.assertNotIn(uses['stats["b"]']['id'], trace_a['eventIds'])

        outer_stats = next(row for row in nodes if row['kind'] == 'key'
                           and row['name'].endswith("['stats']"))
        context_events = {row['details']['key']: row for row in flow['events']
                          if row['kind'] == 'template_context'}
        self.assertIn(outer_stats['id'], context_events['stats']['inputs'])
        self.assertNotIn(outer_stats['id'], context_events['other']['inputs'])
        outer_trace = build_dataflow(model, scope['id'], node_id=outer_stats['id'],
                                     direction='downstream')['trace']
        self.assertIn(context_events['stats']['id'], outer_trace['eventIds'])
        self.assertNotIn(context_events['other']['id'], outer_trace['eventIds'])

    def test_trace_and_budgets(self):
        flow = self.flow('edit_values')
        returned = next(node for node in flow['nodes'] if node['kind'] == 'output')
        trace = self.flow('edit_values', node_id=returned['id'], direction='upstream')['trace']
        self.assertIn(returned['id'], trace['nodeIds'])
        self.assertTrue(trace['eventIds'])
        with self.assertRaisesRegex(ValueError, 'unknown data-flow node'):
            self.flow('edit_values', node_id='missing')
        with self.assertRaisesRegex(ValueError, 'direction'):
            self.flow('edit_values', direction='sideways')
        limited = self.flow('dashboard', max_events=5, max_edges=10, max_models=1)
        self.assertTrue(limited['truncated'])
        self.assertLessEqual(len(limited['events']), 5)
        self.assertLessEqual(len(limited['edges']), 10)
        self.assertIsInstance(limited['omitted'], int)
        first = self.flow('dashboard', max_models=1)
        second = self.flow('dashboard', max_models=1, model_offset=1)
        self.assertEqual(first['modelTotal'], second['modelTotal'])
        self.assertGreater(first['modelTotal'], 1)
        self.assertEqual(first['nextModelOffset'], 1)
        self.assertNotEqual(first['models'][0]['id'], second['models'][0]['id'])
        self.assertEqual([row['id'] for row in first['nodes']],
                         [row['id'] for row in second['nodes']])

    def test_model_field_limit_is_explicit_and_source_linked(self):
        fields = ''.join(f'    f{index}: int\n' for index in range(230))
        (self.root / 'wide.py').write_text('class Wide:\n' + fields +
                                            '\ndef use(item: Wide):\n    return item\n')
        model = analyze(self.root)
        scope = next(row for row in model['scopes'].values()
                     if row['file'] == 'wide.py' and row['name'] == 'use')
        flow = build_dataflow(model, scope['id'])
        wide = next(row for row in flow['models'] if row['name'] == 'Wide')
        self.assertEqual(len(wide['fields']), 200)
        self.assertEqual(wide['omittedFields'], 30)
        self.assertTrue(wide['fieldsTruncated'])
        self.assertEqual(wide['span']['file'], 'wide.py')
        self.assertTrue(flow['truncated'])
        self.assertTrue(any(row['kind'] == 'model_field_limit' for row in flow['gaps']))

    def test_colon_in_filename_does_not_break_scope_lookup(self):
        source = 'def f(value):\n    return value\n'
        (self.root / 'part:one.py').write_text(source)
        model = analyze(self.root)
        scope = next(row for row in model['scopes'].values()
                     if row['file'] == 'part:one.py' and row['name'] == 'f')
        flow = build_dataflow(model, scope['id'])
        self.assertEqual(flow['scope']['name'], 'f')
        self.assertTrue(any(event['kind'] == 'return' for event in flow['events']))

    def test_plain_name_assignment_has_no_receiver_lookup(self):
        (self.root / 'plain.py').write_text('def f(value):\n    result = value\n    return result\n')
        model = analyze(self.root)
        scope = next(row for row in model['scopes'].values()
                     if row['file'] == 'plain.py' and row['name'] == 'f')
        flow = build_dataflow(model, scope['id'])
        assignment = next(row for row in flow['events'] if row['kind'] == 'new_value')
        self.assertEqual(assignment['label'], 'new value result')
        self.assertTrue(assignment['inputs'])

    def test_relative_and_dotted_model_references(self):
        package = self.root / 'pkg'
        package.mkdir()
        (package / '__init__.py').write_text('')
        (package / 'models.py').write_text('class Project:\n    unused: int\nclass Task:\n    id: int\nclass Status:\n    COMPLETED = "done"\n')
        (package / 'ui.py').write_text('''
import pkg.models as m
import pkg.models
from .models import Project
from .models import Status
def view():
    a = m.Project()
    b = pkg.models.Task()
    c = Project.unused
    return Project, a, b, c, Status.COMPLETED
''')
        model = analyze(self.root)
        scope = next(row for row in model['scopes'].values()
                     if row['file'] == 'pkg/ui.py' and row['name'] == 'view')
        flow = build_dataflow(model, scope['id'])
        resolved = {row['name']: row for row in flow['models'] if row['status'] == 'indexed'}
        self.assertIn('m.Project', resolved)
        self.assertIn('pkg.models.Task', resolved)
        self.assertIn('Project', resolved)
        self.assertIn('unused', [field['name'] for field in resolved['Project']['fields']])
        self.assertFalse(any(row['name'] == 'Project.unused' for row in flow['models']))
        self.assertFalse(any(row['name'] == 'Status.COMPLETED' for row in flow['models']))

    def test_method_owner_exposes_constructor_field_definition(self):
        flow = self.flow('index')
        owner = next(row for row in flow['models'] if row['qualified'] == 'Controller')
        repo = next(field for field in owner['fields'] if field['name'] == 'repo')
        self.assertEqual(repo['annotation'], 'Repository')
        self.assertEqual(repo['owner'], 'Controller')
        read = next(event for event in flow['events'] if event['kind'] == 'read_declared_field')
        self.assertEqual(read['details']['definitionSpan']['start'], repo['span']['start'])
        self.assertEqual(read['certainty'], 'possible')
        self.assertTrue(any(node['name'] == 'self.repo' and node['kind'] == 'field_read'
                            for node in flow['nodes']))
        self.assertTrue(any(row['kind'] == 'call' and 'self.repo.get' in row['label']
                            for row in flow['events']))

    def test_supported_call_exposes_parameter_return_and_possible_effect_sites(self):
        flow = self.flow('call_mutate')
        call = next(row for row in flow['events'] if row['kind'] == 'call'
                    and row['label'] == 'call mutate')
        link = call['details']['crossMethod']
        self.assertEqual(link['callTargetCertainty'], 'supported')
        self.assertEqual(link['lineageCertainty'], 'possible')
        self.assertTrue(link['executionUnproven'])
        self.assertEqual(link['parameterLinks'][0]['parameter'], 'items')
        self.assertTrue(link['parameterLinks'][0]['argumentNodes'])
        self.assertEqual(link['parameterLinks'][0]['parameterSpan']['file'], 'dashboard.py')
        self.assertIn('len(items)', [row['expression'] for row in link['returnSites']])
        self.assertEqual(link['mutationSites'][0]['parameter'], 'items')
        self.assertTrue(any(row['kind'] == 'possible_callee_mutation' for row in flow['gaps']))
        effect = next(row for row in flow['events'] if row['kind'] == 'possible_callee_mutation')
        returned = next(row for row in flow['nodes'] if row['kind'] == 'output')
        trace = self.flow('call_mutate', node_id=returned['id'], direction='upstream')['trace']
        self.assertIn(effect['id'], trace['eventIds'])

    def test_possible_constructed_receiver_maps_to_method_parameter(self):
        flow = self.flow('call_receiver')
        call = next(row for row in flow['events'] if row['kind'] == 'call'
                    and row['label'] == 'call repo.get')
        cross = call['details']['crossMethod']
        self.assertEqual(cross['callTargetCertainty'], 'possible')
        self.assertEqual(cross['parameterLinks'][0]['parameter'], 'self')
        self.assertTrue(cross['parameterLinks'][0]['argumentNodes'])
        names = {row['id']: row['name'] for row in flow['nodes']}
        self.assertIn('repo', [names[item] for item in cross['parameterLinks'][0]['argumentNodes']])

    def test_parameter_object_writes_do_not_claim_prior_absence_or_presence(self):
        flow = self.flow('unknown_prior_state')
        kinds = {row['kind'] for row in flow['events']}
        self.assertIn('assigned_key', kinds)
        self.assertIn('assigned_field', kinds)
        self.assertIn('possible_remove_key', kinds)
        self.assertIn('possible_remove_field', kinds)
        self.assertNotIn('added_field', kinds)
        self.assertNotIn('added_key', kinds)
        self.assertTrue(any(row['kind'] == 'uncertain_delete' for row in flow['gaps']))

    def test_arbitrary_all_and_shadowed_builtin_do_not_invent_new_list(self):
        for name in ('arbitrary_all', 'shadowed_list'):
            flow = self.flow(name)
            result = next(row for row in flow['nodes'] if row['kind'] == 'call_result')
            self.assertNotIn('objectId', result)
            self.assertNotIn('shape', result)
            self.assertTrue(any(row['kind'] == 'opaque_call_result' for row in flow['gaps']))

    def test_shadowed_template_response_is_not_context_boundary(self):
        (self.root / 'shadowed.py').write_text('''
def TemplateResponse(*args, **kwargs):
    return None
def view(request):
    return TemplateResponse(request, 'dashboard.html', {'data': request},
                            headers={'x-test': 'value'})
''')
        model = analyze(self.root)
        attach_template_assets(model, self.root)
        scope = next(row for row in model['scopes'].values()
                     if row['file'] == 'shadowed.py' and row['name'] == 'view')
        flow = build_dataflow(model, scope['id'])
        self.assertEqual(flow['templates'][0]['status'], 'unknown-provider')
        self.assertFalse(any(row['kind'] == 'template_context' for row in flow['events']))
        self.assertTrue(any(row['kind'] == 'unknown_template_provider' for row in flow['gaps']))

    def test_finally_runs_before_return_and_can_change_returned_object(self):
        flow = self.flow('finally_return')
        mutation = next(row for row in flow['events'] if row['kind'] == 'added_item')
        self.assertTrue(any(guard['kind'] == 'finally' for guard in mutation['guards']))
        self.assertFalse(any(row['kind'] == 'unreachable_source' and 'append' in row['expression']
                             for row in flow['gaps']))
        output = next(row for row in flow['nodes'] if row['kind'] == 'output')
        trace = self.flow('finally_return', node_id=output['id'], direction='upstream')['trace']
        self.assertIn(mutation['id'], trace['eventIds'])


if __name__ == '__main__':
    unittest.main()
