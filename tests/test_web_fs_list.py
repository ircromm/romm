import os
import tempfile
import unittest

from rommanager.web import app


class FsListEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_fs_list_accepts_null_json_body(self):
        resp = self.client.post('/api/fs/list', data='null', content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertIn('items', payload)
        self.assertIn('current_path', payload)

    def test_fs_list_lists_explicit_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            subdir = os.path.join(tmp, 'alpha')
            file_path = os.path.join(tmp, 'beta.txt')
            os.mkdir(subdir)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('ok')

            resp = self.client.post('/api/fs/list', json={'path': tmp})
            self.assertEqual(resp.status_code, 200)
            payload = resp.get_json()

            names = {item['name'] for item in payload['items']}
            self.assertIn('alpha', names)
            self.assertIn('beta.txt', names)
            self.assertEqual(payload['current_path'], tmp)


if __name__ == '__main__':
    unittest.main()
