from odoo.addons.web.tests.test_js import HootCommon, unit_test_error_checker
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestAiSubagentUi(HootCommon):
    def test_embedded(self):
        test_filter = self._generate_hash('@test_ai_agent_loop')
        self.browser_js(
            f'/web/tests/livechat?headless&loglevel=2&preset=desktop&timeout=15000&id={test_filter}',
            '', '', login='admin', timeout=180,
            success_signal='[HOOT] Test suite succeeded',
            error_checker=unit_test_error_checker,
        )
