# -*- coding: utf-8 -*-
##############################################################################
#
#    Odoo, Open Source Management Solution
#    Copyright (C) 2022 Halltic Tech S.L. (https://www.halltic.com)
#                  Tristán Mozos <tristan.mozos@halltic.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from odoo.tests import common, tagged


@tagged('post_install', '-at_install')
class TestL10nEsAeatReport(common.TransientModel):
    def _init_test_model(cls, model_cls):
        """ It builds a model from model_cls in order to test abstract models.
        Note that this does not actually create a table in the database, so
        there may be some unidentified edge cases.

        Requirements: test to be executed at post_install.

        : Args:
            model_cls (odoo.models.BaseModel): Class of model to initialize
        Returns:
            Instance
        """
        registry = cls.env.registry

        model._prepare_setup()
        model._setup_base()
        model._setup_fields()
        model._setup_complete()
        model._auto_init()
        model.init()
        return inst

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._init_test_model(cls, L10nEsAeatTestReport)
        cls.AeatReport = cls.env["l10n.es.aeat.report"]
        cls.period_types = {
            '0A':('2016-01-01', '2016-12-31'),
            '1T':('2016-01-01', '2016-03-31'),
            '2T':('2016-04-01', '2016-06-30'),
            '3T':('2016-07-01', '2016-09-30'),
            '4T':('2016-10-01', '2016-12-31'),
            '01':('2016-01-01', '2016-01-31'),
            '02':('2016-02-01', '2016-02-29'),
            '03':('2016-03-01', '2016-03-31'),
            '04':('2016-04-01', '2016-04-30'),
            '05':('2016-05-01', '2016-05-31'),
            '06':('2016-06-01', '2016-06-30'),
            '07':('2016-07-01', '2016-07-31'),
            '08':('2016-08-01', '2016-08-31'),
            '09':('2016-09-01', '2016-09-30'),
            '10':('2016-10-01', '2016-10-31'),
            '11':('2016-11-01', '2016-11-30'),
            '12':('2016-12-01', '2016-12-31'),
        }
