import os
import mimetypes
import logging

from flask import Blueprint, redirect, url_for, request, abort
from flask import render_template, jsonify, send_file, current_app
from flask_login import login_required
from honeyswarm.models import Hive, PepperJobs, Honeypot, AuthKey, Config
from honeyswarm.models import HoneypotInstance
from flaskcode.utils import write_file, dir_tree, get_file_extension
from honeyswarm.saltapi import pepper_api

honeypots = Blueprint('honeypots', __name__, template_folder="templates")
logger = logging.getLogger(__name__)


@honeypots.route('/')
@login_required
def honeypot_list():

    # List of Availiable HoneyPots
    honey_list = Honeypot.objects

    return render_template(
        "honeypots.html",
        honey_list=honey_list
        )


@honeypots.route('/paginate', methods=["POST"])
@login_required
def honeypot_paginate():

    # Used to check for query strings
    # for k, v in request.form.items():
    #    print(k, v)

    draw = request.form.get("draw")
    start_offset = int(request.form.get("start"))
    per_page = int(request.form.get("length"))

    # Calculate the correct page number
    start_offset = start_offset + per_page
    start_page = int(start_offset / per_page)

    # print(start_offset, start_page, per_page)

    # Check for a column sort
    order_by = request.form.get("order[0][column]")
    order_direction = request.form.get("order[0][dir]")

    if order_direction == "asc":
        direction = "+"
    else:
        direction = "-"

    column = [
        "instance_id",
        "hive_name",
        "honeypot_type",
        "status"
        ][int(order_by)]

    order_string = "{0}{1}".format(direction, column)

    instance_rows = HoneypotInstance.objects().order_by(
        order_string).paginate(
            page=start_page,
            per_page=per_page
        )
    instance_count = instance_rows.total

    # This should be how many matched a search. If no search then total rows
    filtered_records = instance_count

    # Collect all the rows together
    data_rows = []
    for row in instance_rows.items:
        try:
            single_row = {
                "DT_RowId": str(row.id),
                "instance_id": str(row.id),
                "hive_name": row.hive.name,
                "honeypot_type": row.honeypot.honey_type,
                "status": row.status,
                "actions": {
                    "instance_id": str(row.id),
                    "honeypot_name": row.honeypot.name,
                    "report_fields": ",".join(row.honeypot.report_fields)
                    }
            }

            data_rows.append(single_row)
        except Exception as err:
            current_app.logger.error("Error getting Instances: {0}".format(err))
            continue

    # Final Json to return
    json_results = {
        "draw": draw,
        "recordsTotal": instance_count,
        "recordsFiltered": filtered_records,
        "data": data_rows
    }

    return jsonify(json_results)


@honeypots.route('/create/', methods=['POST'])
@login_required
def create_honeypot():

    json_response = {"success": False}

    try:
        new_honeypot = Honeypot()
        new_honeypot.name = request.form.get('honeypot_name')
        new_honeypot.honey_type = request.form.get('honeypot_type')
        new_honeypot.description = request.form.get('honeypot_description')
        new_honeypot.container_name = request.form.get(
            'honeypot_container_name'
            )
        new_honeypot.channels = request.form.get(
            'honeypot_channels'
            ).split('\r\n')
        new_honeypot.report_fields = request.form.get(
            'honeypot_report_fields'
            ).split('\r\n')
        new_honeypot.honeypot_state_file = request.form.get(
            'honeypot_state_file'
            )

        # We need to save here to get the ID then carry on updating
        new_honeypot.save()
        honeypot_id = new_honeypot.id

        # Add a default state file so that we have something to edit.
        state_path = os.path.join(
            current_app.config['FLASKCODE_RESOURCE_BASEPATH'],
            'honeypots', str(honeypot_id)
            )
        state_name = "{0}.sls".format(new_honeypot.honeypot_state_file)
        state_file_path = os.path.join(state_path, state_name)
        if not os.path.exists(state_path):
            os.mkdir(state_path)
            os.mknod(state_file_path)
            os.chmod(state_file_path, 0o777)

        # Add all channels to the master subscriber
        channel_list = request.form.get('honeypot_channels').split('\r\n')

        sub_key = AuthKey.objects(identifier="honeyswarm").first()
        for channel in channel_list:
            if channel not in sub_key.subscribe:
                sub_key.subscribe.append(channel)
        sub_key.save()

        json_response['success'] = True
        json_response['message'] = "Honypot Created"

    except Exception as err:
        json_response['message'] = err
        logger.error("Error creating honeypot ", err)

    return redirect(url_for('honeypots.honeypot_list'))


@honeypots.route('/<honeypot_id>/delete/', methods=['GET'])
@login_required
def delete_honeypot(honeypot_id):
    # This one is harder.
    json_response = {"success": False}

    honeypot = Honeypot.objects(id=honeypot_id).first()

    if not honeypot:
        return abort(404)

    # Remove all the instances from hives
    hives = Hive.objects()
    for hive in hives:
        for instance in hive.honeypots:
            if instance.honeypot == honeypot:
                container_name = honeypot.container_name
                pepper_api.docker_remove(
                    str(hive.id), container_name
                    )
                # remove the instance from the hive honeypot list
                hive.update(pull__honeypots=instance)
                # Delete the instance
                instance.delete()
                hive.save()

    # Remove the Honeypot
    honeypot.delete()
    json_response['success'] = True
    return redirect(url_for('honeypots.honeypot_list'))


@honeypots.route('/<honeypot_id>/edit/')
@login_required
def show_honeypot(honeypot_id):

    honeypot_details = Honeypot.objects(id=honeypot_id).first()

    if not honeypot_details:
        abort(404)

    # Lets hack in flask code.
    honey_salt_base = os.path.join(
        current_app.config['SALT_BASE'],
        'honeypots', honeypot_id
        )

    dirname = os.path.basename(honey_salt_base)
    dtree = dir_tree(honey_salt_base, honey_salt_base + '/')

    # I want to rebuild the tree slightlt differently.
    new_tree = dict(
        name=os.path.basename(honey_salt_base),
        path_name='',
        children=[{
            'name': honeypot_id,
            'path_name': honeypot_id,
            'children': dtree['children']
        }]
    )

    return render_template(
        'flaskcode/honeypot_editor.html',
        honeypot_details=honeypot_details,
        dirname=dirname,
        dtree=new_tree,
        editor_theme="vs-dark",
        honeypot_id=honeypot_id,
        object_id=honeypot_id,
        data_url="honeypots"
        )


@honeypots.route('/<honeypot_id>/update/', methods=['POST'])
@login_required
def update_honeypot(honeypot_id):
    honeypot_details = Honeypot.objects(id=honeypot_id).first()

    if not honeypot_details:
        abort(404)

    form_vars = request.form.to_dict()
    json_response = {"success": False}

    honeypot_details.name = request.form.get('honeypot_name')
    honeypot_details.honey_type = request.form.get('honeypot_type')
    honeypot_details.description = request.form.get('honeypot_description')
    honeypot_details.container_name = request.form.get(
        'honeypot_container_name'
        )
    honeypot_details.channels = request.form.get(
        'honeypot_channels'
        ).split('\r\n')
    honeypot_details.report_fields = request.form.get(
        'honeypot_report_fields'
        ).split('\r\n')
    honeypot_details.honeypot_state_file = request.form.get(
        'honeypot_state_file'
        )

    # Now add any Pillar States
    pillar_states = []
    for field in form_vars.items():
        if field[0].startswith('pillar-key'):
            key_id = field[0].split('-')[-1]
            key_name = field[1]
            key_value = request.form.get("pillar-value-{0}".format(key_id))
            if key_name == '' or key_value == '':
                continue
            pillar_pair = [key_name, key_value]
            pillar_states.append(pillar_pair)

    honeypot_details.pillar = pillar_states

    # Update HoneySwarm HP Master Subscriber
    channel_list = request.form.get('honeypot_channels').split('\r\n')

    honeyswarm_subscriber = AuthKey.objects(identifier="honeyswarm").first()

    if honeyswarm_subscriber:
        for channel in channel_list:
            if channel not in honeyswarm_subscriber.subscribe:
                honeyswarm_subscriber.subscribe.append(channel)
        honeyswarm_subscriber.save()

    honeypot_details.save()
    json_response['success'] = True

    return jsonify(json_response)


@honeypots.route(
    '/<object_id>/resource-data/<path:file_path>.txt',
    methods=['GET', 'HEAD']
    )
@login_required
def resource_data(object_id, file_path):

    honey_salt_base = os.path.join(
        current_app.config['FLASKCODE_RESOURCE_BASEPATH'],
        'honeypots', object_id
        )

    file_path = os.path.join(honey_salt_base, file_path)
    if not (os.path.exists(file_path) and os.path.isfile(file_path)):
        abort(404)
    response = send_file(file_path, mimetype='text/plain', cache_timeout=0)
    mimetype, encoding = mimetypes.guess_type(file_path, False)
    if mimetype:
        response.headers.set('X-File-Mimetype', mimetype)
        extension = mimetypes.guess_extension(
            mimetype, False) or get_file_extension(file_path)
        if extension:
            response.headers.set(
                'X-File-Extension', extension.lower().lstrip('.'))
    if encoding:
        response.headers.set('X-File-Encoding', encoding)
    return response


@honeypots.route(
    '/<object_id>/update-resource-data/<path:file_path>',
    methods=['POST']
    )
@login_required
def update_resource_data(object_id, file_path):
    honey_salt_base = os.path.join(
        current_app.config['FLASKCODE_RESOURCE_BASEPATH'],
        'honeypots', object_id
        )
    file_path = os.path.join(honey_salt_base, file_path)
    is_new_resource = bool(int(request.form.get('is_new_resource', 0)))

    if not is_new_resource and not (
            os.path.exists(file_path) and os.path.isfile(file_path)):
        abort(404)
    success = True
    message = 'File saved successfully'
    resource_data = request.form.get('resource_data', None)
    if resource_data:
        success, message = write_file(resource_data, file_path)
    else:
        success = False
        message = 'File data not uploaded'
    return jsonify({'success': success, 'message': message})


@honeypots.route('/<honeypot_id>/deployments/', methods=['POST'])
@login_required
def honeypot_deployments(honeypot_id):
    honeypot_details = Honeypot.objects(id=honeypot_id).first()

    if not honeypot_details:
        abort(404)

    all_hives = Hive.objects(frame__exists=True, salt_alive=True)

    modal_form = render_template(
        "honeypot_deployment.html",
        all_hives=all_hives,
        honeypot_details=honeypot_details
    )

    json_response = {
        "modal_form": modal_form,
        "honeypot_details": honeypot_details
    }

    return jsonify(json_response)


@honeypots.route('/<honeypot_id>/deploy/', methods=['POST'])
@login_required
def honeypot_deploy(honeypot_id):
    form_vars = request.form.to_dict()
    json_response = {"success": False}

    honeypot_details = Honeypot.objects(id=honeypot_id).first()

    if not honeypot_details:
        json_response['message'] = "Can not find honeypot"
        return jsonify(json_response)

    hive_id = request.form.get('target_hive')

    hive = Hive.objects(id=hive_id).first()
    if not hive:
        json_response['message'] = "Can not find Hive"
        return jsonify(json_response)

    # Does this hive have the correct frame installed
    if not hive.frame:
        json_response['message'] = "Can not find Hive"
        return jsonify(json_response)

    # Do we already have an instance of this honeypot type on this hive?#
    # Get it and its auth_key
    honeypot_instance = None
    for instance in hive.honeypots:
        if instance.honeypot.id == honeypot_details.id:
            honeypot_instance = instance
            auth_key = AuthKey.objects(
                identifier=str(honeypot_instance.id)
                ).first()

    # Else we create an instance and a new auth_key
    if not honeypot_instance:

        # Create honeypot instance
        honeypot_instance = HoneypotInstance(
            honeypot=honeypot_details,
            hive=hive
        )

        honeypot_instance.save()
        instance_id = str(honeypot_instance.id)

        # Create an AuthKey
        auth_key = AuthKey(
            identifier=instance_id,
            secret=instance_id,
            publish=honeypot_details.channels
        )
        auth_key.save()

    instance_id = str(honeypot_instance.id)

    # Now add any Pillar States
    base_config = Config.objects.first()
    config_pillar = {
        "HIVEID": hive_id,
        "HONEYPOTID": honeypot_id,
        "INSTANCEID": instance_id,
        "HPFIDENT": instance_id,
        "HPFSECRET": instance_id,
        "HPFPORT": 10000,
        "HPFSERVER": base_config.broker_host
    }

    for field in form_vars.items():
        if field[0].startswith('pillar-key'):
            key_id = field[0].split('-')[-1]
            key_name = field[1]
            key_value = request.form.get("pillar-value-{0}".format(key_id))
            if key_name == '' or key_value == '':
                continue
            config_pillar[key_name] = key_value

    # update key / config and save again
    auth_key.save()
    honeypot_instance.hpfeeds = auth_key
    honeypot_instance.pillar = config_pillar
    honeypot_instance.save()

    # Create the job
    honeypot_state_file = 'honeypots/{0}/{1}'.format(
        honeypot_details.id,
        honeypot_details.honeypot_state_file
        )

    pillar_string = ", ".join(
        ('"{}": "{}"'.format(*i) for i in config_pillar.items())
        )

    try:
        job_id = pepper_api.apply_state(
            hive_id,
            [
                honeypot_state_file,
                "pillar={{{0}}}".format(pillar_string)
            ]
        )

        hive = Hive.objects(id=hive_id).first()
        job = PepperJobs(
            hive=hive,
            job_id=job_id,
            job_type="Apply Honeypot",
            job_short="Apply State {0}".format(honeypot_details.name),
            job_description="Apply honeypot {0} to Hive {1}".format(
                honeypot_state_file, hive_id
                )
        )
        job.save()

        if honeypot_instance not in hive.honeypots:
            hive.honeypots.append(honeypot_instance)

        hive.save()

        json_response['success'] = True
        json_response['message'] = "Job Created with Job ID: {0}".format(
            str(job.id)
            )
    except Exception as err:
        json_response['message'] = "Error creating job: {0}".format(err)

    return jsonify(json_response)


@honeypots.route('/instance/control/', methods=['POST'])
@login_required
def instance_control():
    json_response = {"success": False, "message": "No action taken"}

    instance_action = request.form.get('action')
    instance_id = request.form.get('instance_id')

    instance = HoneypotInstance.objects(id=instance_id).first()
    hive = instance.hive

    if not instance:
        json_response['message'] = "Unable to find valid hive or instance"
        return jsonify(json_response)

    if instance_action == "delete":
        # Trigger the container to close
        container_name = instance.honeypot.container_name
        remove_container = pepper_api.docker_remove(
            str(hive.id),
            container_name
            )
        if remove_container:
            # remove the instance from the hive honeypot list
            hive.update(pull__honeypots=instance)
            json_response["success"] = True
            json_response['message'] = "Removed instance of {0}".format(
                container_name
                )
            # Delete the instance
            instance.delete()
            hive.save()

    elif instance_action == "stop":
        container_name = instance.honeypot.container_name
        pepper_job_id = pepper_api.docker_control(
            str(hive.id),
            container_name,
            "stop"
        )

        job = PepperJobs(
            hive=hive,
            job_type="Docker State",
            job_id=pepper_job_id,
            job_short="Setting Docker State on {0}".format(container_name),
            job_description="Setting Docker state for honeypot \
                {0} on hive {1} with instance id: {2}".format(
                    container_name,
                    hive.name,
                    instance.id
                ))
        job.save()

        json_response['success'] = True
        json_response['message'] = "<strong>STOP</strong> requested for Honeypot \
                                    <strong>{0}</strong> on Hive \
                                    <strong>{1}</strong>".format(
                                        container_name, hive.name
                                        )
        instance.status = "Pending"

    elif instance_action == "start":
        container_name = instance.honeypot.container_name
        pepper_job_id = pepper_api.docker_control(
            str(hive.id),
            container_name,
            "start"
        )

        job = PepperJobs(
            hive=hive,
            job_type="Docker State",
            job_id=pepper_job_id,
            job_short="Setting Docker State on {0}".format(container_name),
            job_description="Setting Docker state for honeypot \
                {0} on hive {1} with instance id: {2}".format(
                    container_name,
                    hive.name,
                    instance.id
                    )
                )
        job.save()

        json_response['success'] = True
        json_response['message'] = "<strong>START</strong> requested for Honeypot \
                                    <strong>{0}</strong> on Hive \
                                    <strong>{1}</strong>".format(
                                        container_name, hive.name
                                        )
        instance.status = "Pending"

    elif instance_action == "poll":
        container_name = instance.honeypot.container_name
        pepper_job_id = pepper_api.docker_state(
            str(hive.id),
            container_name
        )

        job = PepperJobs(
            hive=hive,
            job_type="Docker State",
            job_id=pepper_job_id,
            job_short="Checking Docker State on {0}".format(container_name),
            job_description="Checking Docker state for honeypot \
                {0} on hive {1} with instance id: {2}".format(
                    container_name,
                    hive.name,
                    instance.id
                    )
                )
        job.save()

        json_response['success'] = True
        json_response['message'] = "<strong>Checking</strong> state for Honeypot \
                                    <strong>{0}</strong> on Hive \
                                    <strong>{1}</strong>".format(
                                        container_name, hive.name
                                        )
        instance.status = "Pending"

    instance.save()
    hive.save()

    return jsonify(json_response)
