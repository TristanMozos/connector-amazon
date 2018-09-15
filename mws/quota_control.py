#!/usr/bin/env python

import logging
from datetime import datetime

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class RequestDate(models.Model):
    _name = 'amazon.control.date.request'
    request_date = fields.Datetime(required=True)
    request_id = fields.Many2one('amazon.control.request')


class ControlRequest(models.Model):
    _name = 'amazon.control.request'

    request_name = fields.Char(required=True)
    max_quota = fields.Integer(required=True)
    restore_rate = fields.Float(required=True)  # The restore rate quota is expresed in seconds
    max_request_quota_time = fields.Integer()
    max_request_quota_units = fields.Integer()
    units_of_mesaure_quota = fields.Selection(selection=[('sec', 'Seconds'),
                                                         ('min', 'Minutes'),
                                                         ('hor', 'Hours'),
                                                         ('day', 'Days'), ])

    request_date_ids = fields.One2many('amazon.control.date.request', 'request_id')

    @api.model
    def use_quota_if_avaiable(self, request_name):
        # TODO: finish the method to control the quota of the methods
        assert request_name
        control = self.search([('request_name', '=', request_name)])
        try:
            assert control
        except AssertionError:
            _logger.error("The action %s doesn't exist on the quota control module", request_name)
            raise

        self.env['amazon.control.date.request'].create({'request_id':control.id, 'request_date':datetime.now().isoformat()})
