# Odoo Custom Addons

## ai_debug — Live Tracer for the AI Agentic Loop

### Setup

1. **Add this directory to the addons path** when starting `odoo-bin`:

   ```bash
   ./odoo-bin --addons-path=odoo/addons,enterprise,custom
   ```

2. **Install the `ai_debug` module** (requires `ai_app` and `bus`):

   ```bash
   ./odoo-bin --addons-path=odoo/addons,enterprise,custom -d mydb -i ai_debug
   ```

3. **Navigate to** [`/ai-debug`](http://localhost:8069/ai-debug) in your browser.
