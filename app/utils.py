#
# IM - Infrastructure Manager Dashboard
# Copyright (C) 2020 - GRyCAP - Universitat Politecnica de Valencia
#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
""" Util functions """

import json
import yaml
import requests
import os
import io
import ast
import time
from flask import flash, g
from app import appdb
from fnmatch import fnmatch
from hashlib import md5
from urllib.parse import urlparse
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

from libcloud.compute.types import Provider
from libcloud.compute.providers import get_driver

import libcloud.security
libcloud.security.VERIFY_SSL_CERT = False
import urllib3
urllib3.disable_warnings(InsecureRequestWarning)

SITE_LIST = {}
LAST_UPDATE = 0
CACHE_DELAY = 3600


def _getStaticSitesInfo():
    if g.settings.static_sites:
        return g.settings.static_sites
    if g.settings.static_sites_url:
        # TODO: Donwload and parse
        return {}


def getStaticSitesProjectIDs(serviceid):
    res = []
    for site in _getStaticSitesInfo():
        if serviceid == site["id"]:
            for vo, projectid in site["vos"].items():
                res.append((vo, projectid))

    return res


def getStaticSites(vo=None):
    res = {}
    for site in _getStaticSitesInfo():
        if vo is None or vo in site["vos"]:
            res[site["name"]] = (site["url"], "", site["id"])

    return res


def getStaticVOs():
    res = []
    for site in _getStaticSitesInfo():
        res.extend(list(site["vos"].keys()))

    return list(set(res))


def get_ost_image_url(site_name):
    sites = getCachedSiteList()
    site_url, _, _ = sites[site_name]
    return urlparse(site_url)[1]


def get_site_images(site_name, vo, access_token, cred, userid):
    try:
        domain = None
        creds = cred.get_cred(site_name, userid)
        if creds and "project" in creds and creds["project"]:
            domain = creds["project"]

        sites = getCachedSiteList()
        site_url, _, _ = sites[site_name]

        OpenStack = get_driver(Provider.OPENSTACK)
        driver = OpenStack('egi.eu', access_token,
                           ex_tenant_name='openid',
                           ex_force_auth_url=site_url,
                           ex_force_auth_version='3.x_oidc_access_token',
                           ex_domain_name=domain)

        # Workaround to unset default service_region (RegionOne)
        driver.connection.service_region = None

        images = driver.list_images()
        return [(image.name, image.id) for image in images]
    except Exception as ex:
        msg = "Error loading site images: %s!" % str(ex)
        return [(msg, msg)]


def getUserVOs(entitlements):
    vos = []
    for elem in entitlements:
        if elem.startswith('urn:mace:egi.eu:group:'):
            vos.append(elem[22:22 + elem[22:].find(':')])
    return vos


def getCachedSiteList():
    global SITE_LIST
    global LAST_UPDATE
    global CACHE_DELAY

    now = int(time.time())
    if not SITE_LIST or now - LAST_UPDATE > CACHE_DELAY:
        LAST_UPDATE = now
        SITE_LIST = getStaticSites()
        SITE_LIST.update(appdb.get_sites())

    if not SITE_LIST:
        flash("Error retrieving site list", 'warning')
        return []
    else:
        return SITE_LIST


def getUserAuthData(access_token, cred, userid):
    global SITE_LIST
    global LAST_UPDATE
    global CACHE_DELAY

    res = "type = InfrastructureManager; token = %s" % access_token

    cont = 0
    for site_name, (site_url, _, _) in getCachedSiteList().items():
        cont += 1
        creds = cred.get_cred(site_name, userid)
        res += "\\nid = ost%s; type = OpenStack; username = egi.eu; " % cont
        res += "tenant = openid; auth_version = 3.x_oidc_access_token;"
        res += " host = %s; password = '%s'" % (site_url, access_token)
        if creds and "project" in creds and creds["project"]:
            res += "; domain = %s" % creds["project"]

    return res


def format_json_radl(vminfo):
    res = {}
    for elem in vminfo:
        if elem["class"] == "system":
            for field, value in elem.items():
                if field not in ["class", "id"]:
                    if field.endswith("_min"):
                        field = field[:-4]
                    res[field] = value
    return res


def to_pretty_json(value):
    return json.dumps(value, sort_keys=True,
                      indent=4, separators=(',', ': '))


def avatar(email, size):
    digest = md5(email.lower().encode('utf-8')).hexdigest()
    return 'https://www.gravatar.com/avatar/{}?d=identicon&s={}'.format(digest, size)


def loadToscaTemplates(directory):

    toscaTemplates = []
    for path, _, files in os.walk(directory):
        for name in files:
            if (fnmatch(name, "*.yml") or fnmatch(name, "*.yaml")) and \
                    not (fnmatch(name, "*.parameters.yaml") or fnmatch(name, "*.parameters.yml")):
                # skip hidden files
                if name[0] != '.':
                    toscaTemplates.append(os.path.relpath(os.path.join(path, name), directory))

    return toscaTemplates


def extractToscaInfo(toscaDir, tosca_pars_dir, toscaTemplates):
    toscaInfo = {}
    for tosca in toscaTemplates:
        with io.open(toscaDir + tosca) as stream:
            template = yaml.full_load(stream)

            toscaInfo[tosca] = {"valid": True,
                                "description": "TOSCA Template",
                                "metadata": {
                                    "icon": "https://cdn4.iconfinder.com/data/icons/mosaicon-04/512/websettings-512.png"
                                },
                                "enable_config_form": False,
                                "inputs": {},
                                "tabs": {}}

            if 'topology_template' not in template:
                toscaInfo[tosca]["valid"] = False
            else:
                if 'description' in template:
                    toscaInfo[tosca]["description"] = template['description']

                if 'metadata' in template and template['metadata'] is not None:
                    for k, v in template['metadata'].items():
                        toscaInfo[tosca]["metadata"][k] = v

                if 'inputs' in template['topology_template']:
                    toscaInfo[tosca]['inputs'] = template['topology_template']['inputs']

                # add parameters code here
                if tosca_pars_dir:
                    tosca_pars_path = tosca_pars_dir + "/"  # this has to be reassigned here because is local.
                    for fpath, _, fnames in os.walk(tosca_pars_path):
                        for fname in fnames:
                            if fnmatch(fname, os.path.splitext(tosca)[0] + '.parameters.yml') or \
                                    fnmatch(fname, os.path.splitext(tosca)[0] + '.parameters.yaml'):
                                # skip hidden files
                                if fname[0] != '.':
                                    tosca_pars_file = os.path.join(fpath, fname)
                                    with io.open(tosca_pars_file) as pars_file:
                                        toscaInfo[tosca]['enable_config_form'] = True
                                        pars_data = yaml.full_load(pars_file)
                                        for key, value in pars_data["inputs"].items():
                                            if "tab" in value:
                                                toscaInfo[tosca]['inputs'][key]["tab"] = value["tab"]
                                        if "tabs" in pars_data:
                                            toscaInfo[tosca]['tabs'] = pars_data["tabs"]

    return toscaInfo


def exchange_token_with_audience(oidc_url, client_id, client_secret, oidc_token, audience):

    payload_string = ('{ "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange", "audience": "' +
                      audience + '", "subject_token": "' + oidc_token + '", "scope": "openid profile" }')

    # Convert string payload to dictionary
    payload = ast.literal_eval(payload_string)

    oidc_response = requests.post(oidc_url + "/token", data=payload, auth=(client_id, client_secret), verify=False)

    if not oidc_response.ok:
        raise Exception("Error exchanging token: {} - {}".format(oidc_response.status_code, oidc_response.text))

    deserialized_oidc_response = json.loads(oidc_response.text)

    return deserialized_oidc_response['access_token']
