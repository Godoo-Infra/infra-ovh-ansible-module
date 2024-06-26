#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function

from ansible.module_utils.basic import AnsibleModule

__metaclass__ = type

DOCUMENTATION = r"""
---
module: domain
short_description: Manage record in DNS zone
description:
    - Manage record in DNS zone
author: Synthesio SRE Team
requirements:
    - ovh >= 0.5.0
options:
    value:
        required: true
        description: The value, or values as it can be a list, of the record
    name:
        required: true
        description: The name to create/update/delete
    domain:
        required: true
        description: The domain to modify
    record_type:
        required: false
        description: The DNS record type (A AAAA CAA CNAME DKIM DMARC DNAME LOC MX NAPTR NS PTR SPF SRV SSHFP TLSA TXT)
        default: A
    state:
        required: false
        description: Indicate the desired state for the record
        default: present
    append:
        required: false
        description: Keep existings values and append
        description: This switch allows to have multiple record for the same name with different values. It will append values to existing one.
        default: false
    ttl:
        required: false
        default: 0
        description: Time To live for the given record

"""

EXAMPLES = r"""
- name: Ensure entry is in dns
  synthesio.ovh.domain:
    domain: example.com
    value: "192.2.0.1"
    name: "www"
    state: "present"
  delegate_to: localhost
"""

RETURN = """ # """

from ansible_collections.synthesio.ovh.plugins.module_utils.ovh import (
    ovh_api_connect,
    ovh_argument_spec,
)

try:
    from ovh.exceptions import APIError

    HAS_OVH = True
except ImportError:
    HAS_OVH = False


def run_module():
    module_args = ovh_argument_spec()
    module_args.update(
        dict(
            value=dict(required=True, type="list"),
            name=dict(required=True),
            domain=dict(required=True),
            record_type=dict(
                choices=[
                    "A",
                    "AAAA",
                    "CAA",
                    "CNAME",
                    "DKIM",
                    "DMARC",
                    "DNAME",
                    "LOC",
                    "MX",
                    "NAPTR",
                    "NS",
                    "PTR",
                    "SPF",
                    "SRV",
                    "SSHFP",
                    "TLSA",
                    "TXT",
                ],
                default="A",
            ),
            state=dict(choices=["present", "absent"], default="present"),
            record_ttl=dict(type="int", required=False, default=0),
            append=dict(required=False, default=False, type="bool"),
        )
    )

    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)
    client = ovh_api_connect(module)

    value = module.params["value"]
    domain = module.params["domain"]
    name = module.params["name"]
    record_type = module.params["record_type"]
    state = module.params["state"]
    append = module.params["append"]
    record_ttl = module.params["record_ttl"]

    if module.check_mode:
        # TODO
        # This check mode exit is not accurate.
        # It has to be rewritten to reflect different actions
        module.exit_json(
            msg=f"{', '.join(value)} set to {name}.{domain} ! - (dry run mode)"
        )

    try:
        existing_records = client.get(
            f"/domain/zone/{domain}/record", fieldType=record_type, subDomain=name
        )
    except APIError as api_error:
        module.fail_json(msg=f"Failed to call OVH API: {api_error}")

    record_created = []
    record_deleted = []

    # How record is handled
    # A record (here) is composed with a name, a value and a type.
    # - if we have existant record:
    #   - if the value is *not* in the value of the module:
    #     - if the parameter 'append' is set: ==> keep the record
    #     - else: ==> delete the record
    #   - if the value is in the value of the module: ==> keep the record
    #     and complete with other values if any
    # - if there is no record: ==> create record for each value in the module

    if state == "present":
        if existing_records:
            for record_id in existing_records:
                try:
                    record = client.get(f"/domain/zone/{domain}/record/{record_id}")
                except APIError as api_error:
                    module.fail_json(msg=f"Failed to call OVH API: {api_error}")
                # If the record exist with the desired value
                # we can remove the value from the list to be created later
                if record["target"] in value:
                    value.remove(record["target"])

                # If the record exist with an unwanted value, and we must not append it,
                # we will removed it from the zone.
                elif record["target"] not in value and not append:
                    try:
                        client.delete(f"/domain/zone/{domain}/record/{record_id}")
                    except APIError as api_error:
                        module.fail_json(msg=f"Failed to call OVH API: {api_error}")
                    record_deleted.append(record["target"])

        for v in value:
            try:
                client.post(
                    f"/domain/zone/{domain}/record",
                    fieldType=record_type,
                    subDomain=name,
                    target=v,
                    ttl=record_ttl,
                )
                record_created.append(v)
            except APIError as api_error:
                module.fail_json(msg=f"Failed to call OVH API: {api_error}")

        if len(record_deleted) + len(record_created):
            # we must run a refresh on zone after modifications
            try:
                client.post(f"/domain/zone/{domain}/refresh")
            except APIError as api_error:
                module.fail_json(msg=f"Failed to call OVH API: {api_error}")

            msg = ""
            if len(record_deleted):
                msg += f"{', '.join(record_deleted)} deleted"
            if len(record_created):
                if len(record_deleted):
                    msg += " and "
                msg += f"{', '.join(record_created)} created"
            msg += f" from record {name}.{domain}"

            module.exit_json(msg=msg, changed=True)
        else:
            module.exit_json(
                msg=f"{name} is already up-to-date on domain {domain}",
                changed=False,
            )

    elif state == "absent":
        if not existing_records:
            module.exit_json(
                msg=f"Target {name} doesn't exist on domain {domain}",
                changed=False,
            )

        for record_id in existing_records:
            try:
                record = client.get(f"/domain/zone/{domain}/record/{record_id}")
            except APIError as api_error:
                module.fail_json(msg=f"Failed to call OVH API: {api_error}")

            if record["target"] in value:
                try:
                    client.delete(f"/domain/zone/{domain}/record/{record_id}")
                except APIError as api_error:
                    module.fail_json(msg=f"Failed to call OVH API: {api_error}")
                record_deleted.append(record["target"])

        # we must run a refresh on zone after modifications
        try:
            client.post(f"/domain/zone/{domain}/refresh")
        except APIError as api_error:
            module.fail_json(msg=f"Failed to call OVH API: {api_error}")

        module.exit_json(
            msg=f"{', '.join(record_deleted)} deleted from record {name}.{domain}",
            changed=True,
        )


def main():
    run_module()


if __name__ == "__main__":
    main()
