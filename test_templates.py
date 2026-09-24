"""Template references remain source-only, bounded snapshot candidates."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from threadline.analyzer import analyze
from threadline.service import SnapshotStore
from threadline.templates import attach_template_assets, literal_template_names

TEMPLATE_SETUP = ('from fastapi.templating import Jinja2Templates\n'
                  'templates = Jinja2Templates(directory="templates")\n')


class TemplateAssetTests(unittest.TestCase):
    def test_literal_name_discovery_for_git_baselines(self):
        names = literal_template_names({
            'ui.py': TEMPLATE_SETUP + 'templates.TemplateResponse("dashboard.html", {})\n'
                     'templates.TemplateResponse(dynamic_name, {})\n',
            'other.py': TEMPLATE_SETUP + 'templates.TemplateResponse(request, "admin/card.html", {})\n',
        })
        self.assertEqual(names, {'dashboard.html', 'admin/card.html'})

    def test_literal_context_and_later_client_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'ui.py').write_text(
                TEMPLATE_SETUP +
                'def dashboard(request, projects):\n'
                '    return templates.TemplateResponse(request, "dashboard.html", '
                '{"request": request, "recent_projects": projects}, '
                'headers={"NotContext": "x"})\n')
            template = root / 'templates' / 'dashboard.html'
            template.parent.mkdir()
            template.write_text(
                '{% for project in recent_projects %}\n'
                '  {{ project.task_count }}\n'
                '{% endfor %}\n'
                "<script>apiFetch('/agents/usage')</script>\n")
            model = analyze(root)
            attach_template_assets(model, root)
            self.assertEqual(len(model['templateLinks']), 1)
            link = model['templateLinks'][0]
            self.assertEqual(link['status'], 'matched')
            self.assertEqual(link['candidates'], ['templates/dashboard.html'])
            self.assertEqual(link['contextKeys'], ['recent_projects', 'request'])
            self.assertIn('dashboard', model['scopes'][link['scope']]['qualified'])
            asset = model['templateAssets']['templates/dashboard.html']
            self.assertEqual(asset['clientFetches'][0]['path'], '/agents/usage')
            self.assertEqual(asset['clientFetches'][0]['kind'], 'later-client-request')
            self.assertTrue(any(use['expression'] == 'project.task_count'
                                for use in asset['uses']))
            self.assertTrue(any(use['contextKey'] == 'recent_projects'
                                and use.get('path') == 'project.task_count'
                                for use in link['contextUses']))
            self.assertEqual(model['templateManifest']['templates/dashboard.html']['hash'],
                             asset['hash'])

    def test_ambiguous_name_and_symlink_are_not_promoted(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            (root / 'ui.py').write_text(
                TEMPLATE_SETUP +
                'def view():\n'
                '    return templates.TemplateResponse("card.html", {})\n')
            for folder in ('a', 'b'):
                path = root / folder / 'card.html'
                path.parent.mkdir()
                path.write_text('{{ title }}')
            (Path(outside) / 'card.html').write_text('{{ secret }}')
            try:
                (root / 'outside').symlink_to(outside, target_is_directory=True)
            except (NotImplementedError, OSError):
                pass
            model = analyze(root)
            attach_template_assets(model, root)
            link = model['templateLinks'][0]
            self.assertEqual(link['status'], 'ambiguous')
            self.assertEqual(set(link['candidates']), {'a/card.html', 'b/card.html'})
            self.assertNotIn('outside/card.html', model['templateAssets'])

    def test_template_edits_change_manifest_and_dynamic_names_stay_uncertain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'ui.py').write_text(
                TEMPLATE_SETUP +
                'def view(name):\n'
                '    return templates.TemplateResponse(name, {})\n'
                'def fixed():\n'
                '    return templates.TemplateResponse("card.html", {})\n')
            template = root / 'card.html'
            template.write_text('{{ one }}')
            first = analyze(root)
            attach_template_assets(first, root)
            self.assertEqual(first['templateLinks'][0]['status'], 'dynamic')
            initial_hash = first['templateManifest']['card.html']['hash']
            template.write_text('{{ two }}')
            second = analyze(root)
            attach_template_assets(second, root)
            self.assertNotEqual(initial_hash, second['templateManifest']['card.html']['hash'])

    def test_template_source_is_pinned_to_its_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'ui.py').write_text(
                TEMPLATE_SETUP +
                'def view():\n'
                '    return templates.TemplateResponse("card.html", {})\n')
            template = root / 'card.html'
            template.write_text('{{ before }}')
            store = SnapshotStore(root)
            first_id = store.refresh()['snapshotId']
            template.write_text('{{ after }}')
            second_id = store.refresh()['snapshotId']
            self.assertNotEqual(first_id, second_id)
            self.assertEqual(store.get_source(snapshot_id=first_id, file='card.html',
                                              start=1, end=1)['source'], '{{ before }}')
            self.assertEqual(store.get_source(snapshot_id=second_id, file='card.html',
                                              start=1, end=1)['source'], '{{ after }}')

    def test_shadowed_and_unknown_template_providers_do_not_link_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'ui.py').write_text(
                TEMPLATE_SETUP +
                'def supported(request):\n'
                '    return templates.TemplateResponse(request, "good.html", {})\n'
                'def shadowed(templates, request):\n'
                '    return templates.TemplateResponse(request, "secret.html", {})\n'
                'def local_name():\n'
                '    def TemplateResponse(name, context):\n'
                '        return context\n'
                '    return TemplateResponse("secret.html", {})\n')
            (root / 'good.html').write_text('{{ title }}')
            (root / 'secret.html').write_text('{{ secret }}')
            model = analyze(root)
            attach_template_assets(model, root)
            statuses = {model['scopes'][link['scope']]['name']: link['status']
                        for link in model['templateLinks']}
            self.assertEqual(statuses['supported'], 'matched')
            self.assertEqual(statuses['shadowed'], 'unknown-provider')
            self.assertEqual(statuses['local_name'], 'unknown-provider')
            self.assertNotIn('secret.html', model['templateAssets'])
            self.assertTrue(any('provider is unknown' in gap['reason']
                                for gap in model['templateGaps']))


if __name__ == '__main__':
    unittest.main()
