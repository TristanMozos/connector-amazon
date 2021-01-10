# -*- coding: utf-8 -*-
# Copyright 2018 Halltic eSolutions S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import datetime
from datetime import datetime, timedelta

from odoo import fields, models, api, _
from odoo.exceptions import UserError

class WizardGetDuplicateAmazonProductBackend(models.TransientModel):
    _name = "amazon.duplicate.product.backend.wizard"
    _description = "Get duplicate amazon products on several backends Wizard"

    @api.multi
    def name_get(self):
        result = []
        for wizard in self:
            name = 'Wizard to get duplicate Amazon product on several backends'
            result.append((wizard.id, name))
        return result

    @api.multi
    def get_action_wizard(self):
        self.env['amazon.product.product'].search()



