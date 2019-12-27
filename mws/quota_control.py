#!/usr/bin/env python

import logging
from datetime import datetime
from math import ceil

from odoo import models, fields, api
from odoo.addons.queue_job.exception import FailedJobError, RetryableJobError

_logger = logging.getLogger(__name__)


class RequestDate(models.Model):
    _name = 'amazon.control.date.request'
    request_date = fields.Datetime(required=True)
    request_id = fields.Many2one('amazon.control.request')
    backend_id = fields.Many2one('amazon.backend', required=True)


class ControlRequest(models.Model):
    _name = 'amazon.control.request'

    request_name = fields.Char(required=True)
    max_quota = fields.Integer(required=True)
    restore_rate = fields.Float(required=True)  # The restore rate quota is expressed in seconds
    max_request_quota_time = fields.Integer()
    max_request_quota_units = fields.Integer()
    units_of_mesaure_quota = fields.Selection(selection=[('sec', 'Seconds'),
                                                         ('min', 'Minutes'),
                                                         ('hor', 'Hours'),
                                                         ('day', 'Days'), ])

    request_date_ids = fields.One2many('amazon.control.date.request', 'request_id')

    @api.model
    def use_quota_if_avaiable(self, request_name, backend_id):
        # TODO: finish the method to control the quota of the methods
        assert request_name
        control = self.search([('request_name', '=', request_name)])
        try:
            assert control
        except AssertionError:
            raise FailedJobError("The action %s doesn't exist on the quota control module (MWS)" % request_name)

        last_requests = self.env['amazon.control.date.request'].search([('backend_id', '=', backend_id),
                                                                        ('request_id', '=', control.id)],
                                                                       order='request_date desc',
                                                                       limit=control.max_quota - ceil(control.max_quota / 3))
        time_now = datetime.now()
        if last_requests and len(last_requests) >= control.max_quota - ceil(control.max_quota / 3):
            first_date_request = datetime.strptime(last_requests[len(last_requests) - 1].request_date, '%Y-%m-%d %H:%M:%S')
            if (time_now - first_date_request).seconds < control.restore_rate:
                raise RetryableJobError("The quota of %s is empty (MWS)" % request_name, seconds=ceil(control.restore_rate * 1.2), ignore_retry=True)

        if control.max_request_quota_time > 0:
            last_requests = self.env['amazon.control.date.request'].search([('backend_id', '=', backend_id),
                                                                            ('request_id', '=', control.id)],
                                                                           order='request_date desc',
                                                                           limit=control.max_request_quota_time)

            max_request_factor = 1
            if control.units_of_mesaure_quota == 'min':
                max_request_factor = 60
            if control.units_of_mesaure_quota == 'hor':
                max_request_factor = 60 * 60
            if control.units_of_mesaure_quota == 'day':
                max_request_factor = 60 * 60 * 24

            if last_requests and len(last_requests) >= control.max_request_quota_time:
                first_date_request = datetime.strptime(last_requests[len(last_requests) - 1].request_date, '%Y-%m-%d %H:%M:%S')
                if (time_now - first_date_request).seconds < (control.max_request_quota_units * max_request_factor):
                    raise RetryableJobError("The quota of %s is empty (MWS)" % request_name, seconds=ceil(control.restore_rate * 1.2), ignore_retry=True)

        self.env['amazon.control.date.request'].create({'backend_id':backend_id, 'request_id':control.id, 'request_date':time_now.isoformat()})

    def throw_retry_exception_for_throttled(self, request_name, backend_id, ignore_retry=True):
        control = self.search([('request_name', '=', request_name)])
        time_now = datetime.now()
        i = 0
        while i < control.max_quota:
            self.env['amazon.control.date.request'].create({'backend_id':backend_id, 'request_id':control.id, 'request_date':time_now.isoformat()})
            i += 1

        raise RetryableJobError("MWS API has been an error produced on %s for Request Throttled" % request_name,
                                seconds=ceil(control.restore_rate) + 1,
                                ignore_retry=ignore_retry)
