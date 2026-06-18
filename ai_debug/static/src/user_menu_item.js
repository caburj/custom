/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { session } from "@web/session";

// Module-level mirror of the per-user bypass flag. Seeded from session_info
// (set by ai_debug/models/ir_http.session_info), then read by the user-menu
// item factory on every dropdown open and updated by the toggle callback.
//
// We don't need a reactive object: the user menu re-runs `getElements()` every
// time the dropdown opens, and the CheckBox component flips its own DOM state
// synchronously inside its onChange handler -- so by the time the dropdown
// reopens, getElements returns the new value and the visual matches the
// server. Fire-and-forget the persist call so the toggle feels instant.
let bypassEnabled = Boolean(session.ai_debug_bypass_confirmation);

function bypassConfirmationItem(env) {
    return {
        type: "switch",
        id: "ai_debug_bypass_confirmation",
        // Debug-only: avoids surprising regular users with a destructive
        // toggle they have no reason to flip. Devs running ai_debug already
        // have developer mode on.
        hide: !env.debug,
        description: _t("AI Debug: bypass tool confirmation"),
        isChecked: bypassEnabled,
        // The same callback is wired to both DropdownItem.onSelected (row
        // click) and CheckBox.onChange (checkbox click). The checkbox stops
        // event propagation, so exactly one of the two fires per user
        // gesture. Callback ignores its arg and just inverts the source of
        // truth -- no double-toggle risk.
        callback: () => {
            bypassEnabled = !bypassEnabled;
            env.services.orm.call(
                "res.users",
                "set_ai_debug_bypass_confirmation",
                [],
                { value: bypassEnabled },
            );
        },
        // Slot between "My Preferences" (50) and "My Odoo.com Account" (60).
        sequence: 55,
    };
}

registry.category("user_menuitems").add(
    "ai_debug_bypass_confirmation",
    bypassConfirmationItem,
);
