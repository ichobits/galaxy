import logging
import os
import urllib
import json

from markupsafe import escape
import paste.httpexceptions
from six import string_types, text_type
from sqlalchemy import false, true

from galaxy import datatypes, model, util, web
from galaxy import managers
from galaxy.datatypes.display_applications.util import decode_dataset_user, encode_dataset_user
from galaxy.exceptions import RequestParameterInvalidException
from galaxy.model.item_attrs import UsesAnnotations, UsesItemRatings
from galaxy.util import inflector, smart_str
from galaxy.util.sanitize_html import sanitize_html
from galaxy.web import form_builder
from galaxy.web.base.controller import BaseUIController, ERROR, SUCCESS, url_for, UsesExtendedMetadataMixin
from galaxy.web.framework.helpers import grids, iff, time_ago, to_unicode

log = logging.getLogger(__name__)

comptypes = []

try:
    import zlib  # noqa: F401
    comptypes.append('zip')
except ImportError:
    pass


class HistoryDatasetAssociationListGrid(grids.Grid):
    # Custom columns for grid.
    class HistoryColumn(grids.GridColumn):
        def get_value(self, trans, grid, hda):
            return escape(hda.history.name)

    class StatusColumn(grids.GridColumn):
        def get_value(self, trans, grid, hda):
            if hda.deleted:
                return "deleted"
            return ""

        def get_accepted_filters(self):
            """ Returns a list of accepted filters for this column. """
            accepted_filter_labels_and_vals = {"Active" : "False", "Deleted" : "True", "All": "All"}
            accepted_filters = []
            for label, val in accepted_filter_labels_and_vals.items():
                args = {self.key: val}
                accepted_filters.append(grids.GridColumnFilter(label, args))
            return accepted_filters

    # Grid definition
    title = "Saved Datasets"
    model_class = model.HistoryDatasetAssociation
    default_sort_key = "-update_time"
    columns = [
        grids.TextColumn("Name", key="name",
                         # Link name to dataset's history.
                         link=(lambda item: iff(item.history.deleted, None, dict(operation="switch", id=item.id))), filterable="advanced", attach_popup=True),
        HistoryColumn("History", key="history", sortable=False, target="inbound",
                      link=(lambda item: iff(item.history.deleted, None, dict(operation="switch_history", id=item.id)))),
        grids.IndividualTagsColumn("Tags", key="tags", model_tag_association_class=model.HistoryDatasetAssociationTagAssociation, filterable="advanced", grid_name="HistoryDatasetAssocationListGrid"),
        StatusColumn("Status", key="deleted", attach_popup=False),
        grids.GridColumn("Last Updated", key="update_time", format=time_ago),
    ]
    columns.append(
        grids.MulticolFilterColumn(
            "Search",
            cols_to_filter=[columns[0], columns[2]],
            key="free-text-search", visible=False, filterable="standard")
    )
    operations = [
        grids.GridOperation("Copy to current history", condition=(lambda item: not item.deleted), async_compatible=True),
    ]
    standard_filters = []
    default_filter = dict(name="All", deleted="False", tags="All")
    preserve_state = False
    use_async = True
    use_paging = True
    num_rows_per_page = 50

    def build_initial_query(self, trans, **kwargs):
        # Show user's datasets that are not deleted, not in deleted histories, and not hidden.
        # To filter HDAs by user, need to join model class/HDA and History table so that it is
        # possible to filter by user. However, for dictionary-based filtering to work, need a
        # primary table for the query.
        return trans.sa_session.query(self.model_class).select_from(self.model_class.table.join(model.History.table)) \
            .filter(model.History.user == trans.user) \
            .filter(self.model_class.deleted == false()) \
            .filter(model.History.deleted == false()) \
            .filter(self.model_class.visible == true())


class DatasetInterface(BaseUIController, UsesAnnotations, UsesItemRatings, UsesExtendedMetadataMixin):

    stored_list_grid = HistoryDatasetAssociationListGrid()

    def __init__(self, app):
        super(DatasetInterface, self).__init__(app)
        self.history_manager = managers.histories.HistoryManager(app)
        self.hda_manager = managers.hdas.HDAManager(app)

    def _get_job_for_dataset(self, trans, dataset_id):
        '''
        Return the job for the given dataset. This will throw an error if the
        dataset is either nonexistent or inaccessible to the user.
        '''
        hda = trans.sa_session.query(trans.app.model.HistoryDatasetAssociation).get(self.decode_id(dataset_id))
        assert hda and self._can_access_dataset(trans, hda)
        return hda.creating_job

    def _can_access_dataset(self, trans, dataset_association, allow_admin=True, additional_roles=None):
        roles = trans.get_current_user_roles()
        if additional_roles:
            roles = roles + additional_roles
        return (allow_admin and trans.user_is_admin()) or trans.app.security_agent.can_access_dataset(roles, dataset_association.dataset)

    @web.expose
    def errors(self, trans, id):
        hda = trans.sa_session.query(model.HistoryDatasetAssociation).get(self.decode_id(id))

        if not hda or not self._can_access_dataset(trans, hda):
            return trans.show_error_message("Either this dataset does not exist or you do not have permission to access it.")
        return trans.fill_template("dataset/errors.mako", hda=hda)

    @web.expose
    def stdout(self, trans, dataset_id=None, **kwargs):
        trans.response.set_content_type('text/plain')
        stdout = ""
        try:
            job = self._get_job_for_dataset(trans, dataset_id)
            stdout = job.stdout
        except:
            stdout = "Invalid dataset ID or you are not allowed to access this dataset"
        return smart_str(stdout)

    @web.expose
    # TODO: Migrate stderr and stdout to use _get_job_for_dataset; it wasn't tested.
    def stderr(self, trans, dataset_id=None, **kwargs):
        trans.response.set_content_type('text/plain')
        stderr = ""
        try:
            job = self._get_job_for_dataset(trans, dataset_id)
            stderr = job.stderr
        except:
            stderr = "Invalid dataset ID or you are not allowed to access this dataset"
        return smart_str(stderr)

    @web.expose
    def exit_code(self, trans, dataset_id=None, **kwargs):
        trans.response.set_content_type('text/plain')
        exit_code = ""
        try:
            job = self._get_job_for_dataset(trans, dataset_id)
            exit_code = job.exit_code
        except:
            exit_code = "Invalid dataset ID or you are not allowed to access this dataset"
        return exit_code

    @web.expose
    def default(self, trans, dataset_id=None, **kwd):
        return 'This link may not be followed from within Galaxy.'

    @web.expose
    def get_metadata_file(self, trans, hda_id, metadata_name):
        """ Allows the downloading of metadata files associated with datasets (eg. bai index for bam files) """
        data = trans.sa_session.query(trans.app.model.HistoryDatasetAssociation).get(self.decode_id(hda_id))
        if not data or not self._can_access_dataset(trans, data):
            return trans.show_error_message("You are not allowed to access this dataset")

        fname = ''.join(c in util.FILENAME_VALID_CHARS and c or '_' for c in data.name)[0:150]

        file_ext = data.metadata.spec.get(metadata_name).get("file_ext", metadata_name)
        trans.response.headers["Content-Type"] = "application/octet-stream"
        trans.response.headers["Content-Disposition"] = 'attachment; filename="Galaxy%s-[%s].%s"' % (data.hid, fname, file_ext)
        return open(data.metadata.get(metadata_name).file_name)

    def _check_dataset(self, trans, hda_id):
        # DEPRECATION: We still support unencoded ids for backward compatibility
        try:
            data = trans.sa_session.query(trans.app.model.HistoryDatasetAssociation).get(self.decode_id(hda_id))
            if data is None:
                raise ValueError('Invalid reference dataset id: %s.' % hda_id)
        except:
            try:
                data = trans.sa_session.query(trans.app.model.HistoryDatasetAssociation).get(int(hda_id))
            except:
                data = None
        if not data:
            raise paste.httpexceptions.HTTPRequestRangeNotSatisfiable("Invalid reference dataset id: %s." % str(hda_id))
        if not self._can_access_dataset(trans, data):
            return trans.show_error_message("You are not allowed to access this dataset")
        if data.purged:
            return trans.show_error_message("The dataset you are attempting to view has been purged.")
        if data.deleted and not (trans.user_is_admin() or (data.history and trans.get_user() == data.history.user)):
            return trans.show_error_message("The dataset you are attempting to view has been deleted.")
        if data.state == trans.model.Dataset.states.UPLOAD:
            return trans.show_error_message("Please wait until this dataset finishes uploading before attempting to view it.")
        return data

    @web.expose
    @web.json
    def transfer_status(self, trans, dataset_id, filename=None):
        """ Primarily used for the S3ObjectStore - get the status of data transfer
        if the file is not in cache """
        data = self._check_dataset(trans, dataset_id)
        if isinstance(data, string_types):
            return data
        log.debug("Checking transfer status for dataset %s..." % data.dataset.id)

        # Pulling files in extra_files_path into cache is not handled via this
        # method but that's primarily because those files are typically linked to
        # through tool's output page anyhow so tying a JavaScript event that will
        # call this method does not seem doable?
        if data.dataset.external_filename:
            return True
        else:
            return trans.app.object_store.file_ready(data.dataset)

    @web.expose
    def display(self, trans, dataset_id=None, preview=False, filename=None, to_ext=None, offset=None, ck_size=None, **kwd):
        data = self._check_dataset(trans, dataset_id)
        if not isinstance(data, trans.app.model.DatasetInstance):
            return data
        if "hdca" in kwd:
            raise RequestParameterInvalidException("Invalid request parameter 'hdca' encountered.")
        hdca_id = kwd.get("hdca_id", None)
        if hdca_id:
            hdca = self.app.dataset_collections_service.get_dataset_collection_instance(trans, "history", hdca_id)
            del kwd["hdca_id"]
            kwd["hdca"] = hdca
        # Ensure offset is an integer before passing through to datatypes.
        if offset:
            offset = int(offset)
        # Ensure ck_size is an integer before passing through to datatypes.
        if ck_size:
            ck_size = int(ck_size)
        return data.datatype.display_data(trans, data, preview, filename, to_ext, offset=offset, ck_size=ck_size, **kwd)

    @web.expose_api
    def get_edit(self, trans, dataset_id=None, **kwd):
        """Produces the input definitions available to modify dataset attributes"""
        message = None
        status = None
        if dataset_id is not None:
            id = self.decode_id(dataset_id)
            data = trans.sa_session.query(self.app.model.HistoryDatasetAssociation).get(id)
        else:
            trans.log_event("dataset_id is None, cannot load a dataset to edit.")
            return self.message_exception(trans, 'You must provide a dataset id to edit attributes.')
        if data is None:
            trans.log_event("Problem retrieving dataset id (%s)." % dataset_id)
            return self.message_exception(trans, 'The dataset id is invalid.')
        if dataset_id is not None and data.history.user is not None and data.history.user != trans.user:
            trans.log_event("User attempted to edit a dataset they do not own (encoded: %s, decoded: %s)." % (dataset_id, id))
            return self.message_exception(trans, 'The dataset id is invalid.')
        if data.history.user and not data.dataset.has_manage_permissions_roles(trans):
            # Permission setting related to DATASET_MANAGE_PERMISSIONS was broken for a period of time,
            # so it is possible that some Datasets have no roles associated with the DATASET_MANAGE_PERMISSIONS
            # permission.  In this case, we'll reset this permission to the hda user's private role.
            manage_permissions_action = trans.app.security_agent.get_action(trans.app.security_agent.permitted_actions.DATASET_MANAGE_PERMISSIONS.action)
            permissions = {manage_permissions_action : [trans.app.security_agent.get_private_user_role(data.history.user)]}
            trans.app.security_agent.set_dataset_permission(data.dataset, permissions)
        if self._can_access_dataset(trans, data):
            if data.state == trans.model.Dataset.states.UPLOAD:
                return self.message_exception(trans, 'Please wait until this dataset finishes uploading before attempting to edit its metadata.')
            # let's not overwrite the imported datatypes module with the variable datatypes?
            # the built-in 'id' is overwritten in lots of places as well
            ldatatypes = [(dtype_name, dtype_name) for dtype_name, dtype_value in trans.app.datatypes_registry.datatypes_by_extension.iteritems() if dtype_value.allow_datatype_change]
            ldatatypes.sort()
            all_roles = trans.app.security_agent.get_legitimate_roles(trans, data.dataset, 'root')
            data_metadata = [(name, spec) for name, spec in data.metadata.spec.items()]
            converters_collection = [(key, value.name) for key, value in data.get_converter_types().items()]
            can_manage_dataset = trans.app.security_agent.can_manage_dataset(trans.get_current_user_roles(), data.dataset)
            # attribute editing
            attribute_inputs = [{
                'name' : 'name',
                'type' : 'text',
                'label': 'Name',
                'value': data.get_display_name()
            }, {
                'name' : 'info',
                'type' : 'text',
                'area' : True,
                'label': 'Info',
                'value': data.info
            }, {
                'name' : 'annotation',
                'type' : 'text',
                'area' : True,
                'label': 'Annotation',
                'value': self.get_item_annotation_str(trans.sa_session, trans.user, data),
                'help' : 'Add an annotation or notes to a dataset; annotations are available when a history is viewed.'
            }]
            for name, spec in data_metadata:
                if spec.visible:
                    attributes = data.metadata.get_metadata_parameter(name, trans=trans)
                    if type(attributes) is form_builder.SelectField:
                        attribute_inputs.append({
                            'type'      : 'select',
                            'multiple'  : attributes.multiple,
                            'optional'  : attributes.optional,
                            'name'      : name,
                            'label'     : spec.desc,
                            'options'   : attributes.options,
                            'value'     : attributes.value if attributes.multiple else [attributes.value]
                        })
                    elif type(attributes) is form_builder.TextField:
                        attribute_inputs.append({
                            'type'      : 'text',
                            'name'      : name,
                            'label'     : spec.desc,
                            'value'     : attributes.value,
                            'readonly'  : spec.get('readonly')
                        })
            #if data.missing_meta():
            message = 'Required metadata values are missing. Some of these values may not be editable by the user. Selecting "Auto-detect" will attempt to fix these values.'
            status = 'warning'
            # datatype conversion
            conversion_inputs = [{
                'type'      : 'select',
                'name'      : 'target_type',
                'label'     : 'Name',
                'help'      : 'This will create a new dataset with the contents of this dataset converted to a new format.',
                'options'   : [(convert_name, convert_id) for convert_id, convert_name in converters_collection]
            }]
            # datatype changeing
            datatype_inputs = [{
                'type'      : 'select',
                'name'      : 'datatype',
                'label'     : 'New Type',
                'options'   : [(ext_name, ext_id) for ext_id, ext_name in ldatatypes],
                'value'     : [ext_id for ext_id, ext_name in ldatatypes if ext_id == data.ext],
                'help'      : 'This will change the datatype of the existing dataset but not modify its contents. Use this if Galaxy has incorrectly guessed the type of your dataset.',
            }]
            # permissions
            permission_inputs = list()
            if can_manage_dataset:
                permitted_actions = trans.app.model.Dataset.permitted_actions.items()
                saved_role_ids = {}
                for action, roles in trans.app.security_agent.get_permissions(data.dataset).items():
                    for role in roles:
                        saved_role_ids[action.action] = role.id
                for index, action in permitted_actions:
                    if action == trans.app.security_agent.permitted_actions.DATASET_ACCESS:
                        help_text = action.description + '<br/>NOTE: Users must have every role associated with this dataset in order to access it.'
                    else:
                        help_text = action.description
                    permission_inputs.append({
                        'type'      : 'select',
                        'multiple'  : True,
                        'optional'  : True,
                        'name'      : index,
                        'label'     : action.action,
                        'help'      : help_text,
                        'options'   : [(r.name, r.id) for r in all_roles],
                        'value'     : saved_role_ids[action.action] if action.action in saved_role_ids else []
                    })
            elif trans.user:
                if data.dataset.actions:
                    for action, roles in trans.app.security_agent.get_permissions(data.dataset).items():
                        if roles:
                            role_inputs = list()
                            for role in roles:
                                role_inputs.append({
                                    'name'      : role.name + action.action,
                                    'type'      : 'text',
                                    'label'     : action.description,
                                    'value'     : role.name,
                                    'readonly'  : True
                                })
                            permission_inputs.append( {
                                'name'  : action.action,
                                'label' : action.action,
                                'type'  : 'section',
                                'inputs': role_inputs
                            })
                else:
                    permission_inputs.append({
                        'name'      : 'access_public',
                        'type'      : 'text',
                        'label'     : 'Public access',
                        'value'     : 'This dataset is accessible by everyone (it is public).',
                        'readonly'  : True
                    })
            else:
                permission_inputs.append({
                    'name'      : 'no_access',
                    'type'      : 'text',
                    'label'     : 'No access',
                    'value'     : 'Permissions not available (not logged in).',
                    'readonly'  : True
                })

            return {
                'display_name'      : data.get_display_name(),
                'message'           : message,
                'status'            : status,
                'dataset_id'        : dataset_id,
                'can_manage_dataset': can_manage_dataset,
                'attribute_inputs'  : attribute_inputs,
                'conversion_inputs' : conversion_inputs,
                'datatype_inputs'   : datatype_inputs,
                'permission_inputs' : permission_inputs
            }
        else:
            return self.message_exception(trans, 'You do not have permission to edit this dataset\'s ( id: %s ) information.' % str(dataset_id))

    @web.expose_api
    @web.require_login("see all available datasets")
    def set_edit(self, trans, payload=None, **kwd):
        """Allows user to modify parameters of an HDA."""
        def __ok_to_edit_metadata(dataset_id):
            # prevent modifying metadata when dataset is queued or running as input/output
            # This code could be more efficient, i.e. by using mappers, but to prevent slowing down loading a History panel, we'll leave the code here for now
            for job_to_dataset_association in trans.sa_session.query(
                    self.app.model.JobToInputDatasetAssociation).filter_by(dataset_id=dataset_id).all() \
                    + trans.sa_session.query(self.app.model.JobToOutputDatasetAssociation).filter_by(dataset_id=dataset_id).all():
                if job_to_dataset_association.job.state not in [job_to_dataset_association.job.states.OK, job_to_dataset_association.job.states.ERROR, job_to_dataset_association.job.states.DELETED]:
                    return False
            return True
        message = None
        status = 'success'
        dataset_id = payload.get('dataset_id')
        operation = payload.get('operation')
        if dataset_id is not None:
            id = self.decode_id(dataset_id)
            data = trans.sa_session.query(self.app.model.HistoryDatasetAssociation).get(id)
        if operation == 'attributes':
            # The user clicked the Save button on the 'Edit Attributes' form
            data.name = payload.get('name')
            data.info = payload.get('info')
            if __ok_to_edit_metadata(data.id):
                # The following for loop will save all metadata_spec items
                for name, spec in data.datatype.metadata_spec.items():
                    if not spec.get('readonly'):
                        setattr(data.metadata, name, spec.unwrap(payload.get(name) or None))
                data.datatype.after_setting_metadata(data)
                # Sanitize annotation before adding it.
                if payload.get('annotation'):
                    annotation = sanitize_html(payload.get('annotation'), 'utf-8', 'text/html')
                    self.add_item_annotation(trans.sa_session, trans.get_user(), data, annotation)
                # if setting metadata previously failed and all required elements have now been set, clear the failed state.
                if data._state == trans.model.Dataset.states.FAILED_METADATA and not data.missing_meta():
                    data._state = None
                message = 'Attributes updated. %s' % message if message else 'Attributes updated.'
            else:
                message = 'Attributes updated, but metadata could not be changed because this dataset is currently being used as input or output. You must cancel or wait for these jobs to complete before changing metadata.'
                status = 'warning'
            trans.sa_session.flush()
        elif operation == 'datatype':
            # The user clicked the Save button on the 'Change data type' form
            datatype = payload.get('datatype')
            if data.datatype.allow_datatype_change and trans.app.datatypes_registry.get_datatype_by_extension(datatype).allow_datatype_change:
                # prevent modifying datatype when dataset is queued or running as input/output
                if not __ok_to_edit_metadata(data.id):
                    return self.message_exception(trans, 'This dataset is currently being used as input or output.  You cannot change datatype until the jobs have completed or you have canceled them.')
                else:
                    trans.app.datatypes_registry.change_datatype(data, datatype)
                    trans.sa_session.flush()
                    trans.app.datatypes_registry.set_external_metadata_tool.tool_action.execute(trans.app.datatypes_registry.set_external_metadata_tool, trans, incoming={'input1': data}, overwrite=False)  # overwrite is False as per existing behavior
                    message = 'Changed the type to %s.' % datatype
            else:
                return self.message_exception(trans, 'You are unable to change datatypes in this manner. Changing %s to %s is not allowed.' % (data.extension, datatype))
        elif operation == 'autodetect':
            # The user clicked the Auto-detect button on the 'Edit Attributes' form
            # prevent modifying metadata when dataset is queued or running as input/output
            if not __ok_to_edit_metadata(data.id):
                return self.message_exception(trans, 'This dataset is currently being used as input or output.  You cannot change metadata until the jobs have completed or you have canceled them.')
            else:
                for name, spec in data.metadata.spec.items():
                    # We need to be careful about the attributes we are resetting
                    if name not in ['name', 'info', 'dbkey', 'base_name']:
                        if spec.get('default'):
                            setattr(data.metadata, name, spec.unwrap(spec.get('default')))
                message = 'Attributes have been queued to be updated.'
                trans.app.datatypes_registry.set_external_metadata_tool.tool_action.execute(trans.app.datatypes_registry.set_external_metadata_tool, trans, incoming={'input1': data})
                trans.sa_session.flush()
        elif operation == 'conversion':
            target_type = payload.get('target_type')
            if target_type:
                message = data.datatype.convert_dataset(trans, data, target_type)
        elif operation == 'permission':
            if not trans.user:
                return self.message_exception(trans, 'You must be logged in if you want to change permissions.')
            if trans.app.security_agent.can_manage_dataset(trans.get_current_user_roles(), data.dataset):
                permitted_actions = trans.app.model.Dataset.permitted_actions.items()
                payload_permissions = payload.get('permissions')
                # The user associated the DATASET_ACCESS permission on the dataset with 1 or more roles.  We
                # need to ensure that they did not associate roles that would cause accessibility problems.
                permissions, in_roles, error, message = \
                    trans.app.security_agent.derive_roles_from_access(trans, data.dataset.id, 'root', **payload_permissions)
                if error:
                    # Keep the original role associations for the DATASET_ACCESS permission on the dataset.
                    access_action = trans.app.security_agent.get_action(trans.app.security_agent.permitted_actions.DATASET_ACCESS.action)
                    permissions[access_action] = data.dataset.get_access_roles(trans)
                    return self.message_exception(trans, message)
                else:
                    error = trans.app.security_agent.set_all_dataset_permissions(data.dataset, permissions)
                    if error:
                        return self.message_exception(trans, error)
                    else:
                        message = 'Your changes completed successfully.'
                trans.sa_session.refresh(data.dataset)
            else:
                return self.message_exception(trans, 'You are not authorized to change this dataset\'s permissions.')
        else:
            return self.message_exception(trans, 'Invalid operation identifier (%s).' % operation)
        return { 'status': status, 'message': message }

    @web.expose
    @web.json
    @web.require_login("see all available datasets")
    def list(self, trans, **kwargs):
        """List all available datasets"""
        status = message = None

        if 'operation' in kwargs:
            operation = kwargs['operation'].lower()
            hda_ids = util.listify(kwargs.get('id', []))

            # Display no message by default
            status, message = None, None

            # Load the hdas and ensure they all belong to the current user
            hdas = []
            for encoded_hda_id in hda_ids:
                hda_id = self.decode_id(encoded_hda_id)
                hda = trans.sa_session.query(model.HistoryDatasetAssociation).filter_by(id=hda_id).first()
                if hda:
                    # Ensure history is owned by current user
                    if hda.history.user_id is not None and trans.user:
                        assert trans.user.id == hda.history.user_id, "HistoryDatasetAssocation does not belong to current user"
                    hdas.append(hda)
                else:
                    log.warning("Invalid history_dataset_association id '%r' passed to list", hda_id)

            if hdas:
                if operation == "switch" or operation == "switch_history":
                    # Switch to a history that the HDA resides in.

                    # Convert hda to histories.
                    histories = []
                    for hda in hdas:
                        histories.append(hda.history)

                    # Use history controller to switch the history. TODO: is this reasonable?
                    status, message = trans.webapp.controllers['history']._list_switch(trans, histories)

                    # Current history changed, refresh history frame; if switching to a dataset, set hda seek.
                    kwargs['refresh_frames'] = ['history']
                    if operation == "switch":
                        hda_ids = [trans.security.encode_id(hda.id) for hda in hdas]
                        # TODO: Highlighting does not work, has to be revisited
                        trans.template_context['seek_hda_ids'] = hda_ids
                elif operation == "copy to current history":
                    #
                    # Copy datasets to the current history.
                    #

                    target_histories = [trans.get_history()]

                    # Reverse HDAs so that they appear in the history in the order they are provided.
                    hda_ids.reverse()
                    status, message = self._copy_datasets(trans, hda_ids, target_histories)

                    # Current history changed, refresh history frame.
                    kwargs['refresh_frames'] = ['history']

        # Render the list view
        kwargs['dict_format'] = True
        return self.stored_list_grid(trans, status=status, message=message, **kwargs)

    @web.expose
    def imp(self, trans, dataset_id=None, **kwd):
        """ Import another user's dataset via a shared URL; dataset is added to user's current history. """
        # Set referer message.
        referer = trans.request.referer
        if referer:
            referer_message = "<a href='%s'>return to the previous page</a>" % escape(referer)
        else:
            referer_message = "<a href='%s'>go to Galaxy's start page</a>" % url_for('/')
        # Error checking.
        if not dataset_id:
            return trans.show_error_message("You must specify a dataset to import. You can %s." % referer_message, use_panels=True)
        # Do import.
        cur_history = trans.get_history(create=True)
        status, message = self._copy_datasets(trans, [dataset_id], [cur_history], imported=True)
        message = "Dataset imported. <br>You can <a href='%s'>start using the dataset</a> or %s." % (url_for('/'), referer_message)
        return trans.show_message(message, type=status, use_panels=True)

    @web.expose
    @web.json
    @web.require_login("use Galaxy datasets")
    def get_name_and_link_async(self, trans, id=None):
        """ Returns dataset's name and link. """
        decoded_id = self.decode_id(id)
        dataset = self.hda_manager.get_accessible(decoded_id, trans.user)
        dataset = self.hda_manager.error_if_uploading(dataset)
        return_dict = {"name" : dataset.name, "link" : url_for(controller='dataset', action="display_by_username_and_slug", username=dataset.history.user.username, slug=trans.security.encode_id(dataset.id))}
        return return_dict

    @web.expose
    def get_embed_html_async(self, trans, id):
        """ Returns HTML for embedding a dataset in a page. """
        decoded_id = self.decode_id(id)
        dataset = self.hda_manager.get_accessible(decoded_id, trans.user)
        dataset = self.hda_manager.error_if_uploading(dataset)
        if dataset:
            return "Embedded Dataset '%s'" % dataset.name

    @web.expose
    @web.require_login("use Galaxy datasets")
    def set_accessible_async(self, trans, id=None, accessible=False):
        """ Does nothing because datasets do not have an importable/accessible attribute. This method could potentially set another attribute. """
        return

    @web.expose
    @web.require_login("rate items")
    @web.json
    def rate_async(self, trans, id, rating):
        """ Rate a dataset asynchronously and return updated community data. """

        decoded_id = self.decode_id(id)
        dataset = self.hda_manager.get_accessible(decoded_id, trans.user)
        dataset = self.hda_manager.error_if_uploading(dataset)
        if not dataset:
            return trans.show_error_message("The specified dataset does not exist.")

        # Rate dataset.
        self.rate_item(trans.sa_session, trans.get_user(), dataset, rating)

        return self.get_ave_item_rating_data(trans.sa_session, dataset)

    @web.expose
    def display_by_username_and_slug(self, trans, username, slug, filename=None, preview=True):
        """ Display dataset by username and slug; because datasets do not yet have slugs, the slug is the dataset's id. """
        id = slug
        decoded_id = self.decode_id(id)
        dataset = self.hda_manager.get_accessible(decoded_id, trans.user)
        dataset = self.hda_manager.error_if_uploading(dataset)
        if dataset:
            # Filename used for composite types.
            if filename:
                return self.display(trans, dataset_id=slug, filename=filename)

            truncated, dataset_data = self.hda_manager.text_data(dataset, preview)
            dataset.annotation = self.get_item_annotation_str(trans.sa_session, dataset.history.user, dataset)

            # If dataset is chunkable, get first chunk.
            first_chunk = None
            if dataset.datatype.CHUNKABLE:
                first_chunk = dataset.datatype.get_chunk(trans, dataset, 0)

            # If data is binary or an image, stream without template; otherwise, use display template.
            # TODO: figure out a way to display images in display template.
            if isinstance(dataset.datatype, datatypes.binary.Binary) or isinstance(dataset.datatype, datatypes.images.Image) or isinstance(dataset.datatype, datatypes.text.Html):
                trans.response.set_content_type(dataset.get_mime())
                return open(dataset.file_name)
            else:
                # Get rating data.
                user_item_rating = 0
                if trans.get_user():
                    user_item_rating = self.get_user_item_rating(trans.sa_session, trans.get_user(), dataset)
                    if user_item_rating:
                        user_item_rating = user_item_rating.rating
                    else:
                        user_item_rating = 0
                ave_item_rating, num_ratings = self.get_ave_item_rating_data(trans.sa_session, dataset)

                return trans.fill_template_mako("/dataset/display.mako", item=dataset, item_data=dataset_data,
                                                truncated=truncated, user_item_rating=user_item_rating,
                                                ave_item_rating=ave_item_rating, num_ratings=num_ratings,
                                                first_chunk=first_chunk)
        else:
            raise web.httpexceptions.HTTPNotFound()

    @web.expose
    def get_item_content_async(self, trans, id):
        """ Returns item content in HTML format. """

        decoded_id = self.decode_id(id)
        dataset = self.hda_manager.get_accessible(decoded_id, trans.user)
        dataset = self.hda_manager.error_if_uploading(dataset)
        if dataset is None:
            raise web.httpexceptions.HTTPNotFound()
        truncated, dataset_data = self.hda_manager.text_data(dataset, preview=True)
        # Get annotation.
        dataset.annotation = self.get_item_annotation_str(trans.sa_session, trans.user, dataset)
        return trans.stream_template_mako("/dataset/item_content.mako", item=dataset, item_data=dataset_data, truncated=truncated)

    @web.expose
    def annotate_async(self, trans, id, new_annotation=None, **kwargs):
        # TODO:?? why is this an access check only?
        decoded_id = self.decode_id(id)
        dataset = self.hda_manager.get_accessible(decoded_id, trans.user)
        dataset = self.hda_manager.error_if_uploading(dataset)
        if not dataset:
            web.httpexceptions.HTTPNotFound()
        if dataset and new_annotation:
            # Sanitize annotation before adding it.
            new_annotation = sanitize_html(new_annotation, 'utf-8', 'text/html')
            self.add_item_annotation(trans.sa_session, trans.get_user(), dataset, new_annotation)
            trans.sa_session.flush()
            return new_annotation

    @web.expose
    def get_annotation_async(self, trans, id):
        decoded_id = self.decode_id(id)
        dataset = self.hda_manager.get_accessible(decoded_id, trans.user)
        dataset = self.hda_manager.error_if_uploading(dataset)
        if not dataset:
            web.httpexceptions.HTTPNotFound()
        annotation = self.get_item_annotation_str(trans.sa_session, trans.user, dataset)
        if annotation and isinstance(annotation, text_type):
            annotation = annotation.encode('ascii', 'replace')  # paste needs ascii here
        return annotation

    @web.expose
    def display_at(self, trans, dataset_id, filename=None, **kwd):
        """Sets up a dataset permissions so it is viewable at an external site"""
        if not trans.app.config.enable_old_display_applications:
            return trans.show_error_message("This method of accessing external display applications has been disabled by a Galaxy administrator.")
        site = filename
        data = trans.sa_session.query(trans.app.model.HistoryDatasetAssociation).get(dataset_id)
        if not data:
            raise paste.httpexceptions.HTTPRequestRangeNotSatisfiable("Invalid reference dataset id: %s." % str(dataset_id))
        if 'display_url' not in kwd or 'redirect_url' not in kwd:
            return trans.show_error_message('Invalid parameters specified for "display at" link, please contact a Galaxy administrator')
        try:
            redirect_url = kwd['redirect_url'] % urllib.quote_plus(kwd['display_url'])
        except:
            redirect_url = kwd['redirect_url']  # not all will need custom text
        if trans.app.security_agent.dataset_is_public(data.dataset):
            return trans.response.send_redirect(redirect_url)  # anon access already permitted by rbac
        if self._can_access_dataset(trans, data):
            trans.app.host_security_agent.set_dataset_permissions(data, trans.user, site)
            return trans.response.send_redirect(redirect_url)
        else:
            return trans.show_error_message("You are not allowed to view this dataset at external sites.  Please contact your Galaxy administrator to acquire management permissions for this dataset.")

    @web.expose
    def display_application(self, trans, dataset_id=None, user_id=None, app_name=None, link_name=None, app_action=None, action_param=None, action_param_extra=None, **kwds):
        """Access to external display applications"""
        # Build list of parameters to pass in to display application logic (app_kwds)
        app_kwds = {}
        for name, value in dict(kwds).iteritems():  # clone kwds because we remove stuff as we go.
            if name.startswith("app_"):
                app_kwds[name[len("app_"):]] = value
                del kwds[name]
        if kwds:
            log.debug("Unexpected Keywords passed to display_application: %s" % kwds)  # route memory?
        # decode ids
        data, user = decode_dataset_user(trans, dataset_id, user_id)
        if not data:
            raise paste.httpexceptions.HTTPRequestRangeNotSatisfiable("Invalid reference dataset id: %s." % str(dataset_id))
        if user is None:
            user = trans.user
        if user:
            user_roles = user.all_roles()
        else:
            user_roles = []
        # Decode application name and link name
        app_name = urllib.unquote_plus(app_name)
        link_name = urllib.unquote_plus(link_name)
        if None in [app_name, link_name]:
            return trans.show_error_message("A display application name and link name must be provided.")
        if self._can_access_dataset(trans, data, additional_roles=user_roles):
            msg = []
            preparable_steps = []
            refresh = False
            display_app = trans.app.datatypes_registry.display_applications.get(app_name)
            if not display_app:
                log.debug("Unknown display application has been requested: %s", app_name)
                return paste.httpexceptions.HTTPNotFound("The requested display application (%s) is not available." % (app_name))
            dataset_hash, user_hash = encode_dataset_user(trans, data, user)
            try:
                display_link = display_app.get_link(link_name, data, dataset_hash, user_hash, trans, app_kwds)
            except Exception as e:
                log.debug("Error generating display_link: %s", e)
                # User can sometimes recover from, e.g. conversion errors by fixing input metadata, so use conflict
                return paste.httpexceptions.HTTPConflict("Error generating display_link: %s" % e)
            if not display_link:
                log.debug("Unknown display link has been requested: %s", link_name)
                return paste.httpexceptions.HTTPNotFound("Unknown display link has been requested: %s" % link_name)
            if data.state == data.states.ERROR:
                msg.append(('This dataset is in an error state, you cannot view it at an external display application.', 'error'))
            elif data.deleted:
                msg.append(('This dataset has been deleted, you cannot view it at an external display application.', 'error'))
            elif data.state != data.states.OK:
                msg.append(('You must wait for this dataset to be created before you can view it at an external display application.', 'info'))
                refresh = True
            else:
                # We have permissions, dataset is not deleted and is in OK state, allow access
                if display_link.display_ready():
                    if app_action in ['data', 'param']:
                        assert action_param, "An action param must be provided for a data or param action"
                        # data is used for things with filenames that could be passed off to a proxy
                        # in case some display app wants all files to be in the same 'directory',
                        # data can be forced to param, but not the other way (no filename for other direction)
                        # get param name from url param name
                        try:
                            action_param = display_link.get_param_name_by_url(action_param)
                        except ValueError as e:
                            log.debug(e)
                            return paste.httpexceptions.HTTPNotFound(str(e))
                        value = display_link.get_param_value(action_param)
                        assert value, "An invalid parameter name was provided: %s" % action_param
                        assert value.parameter.viewable, "This parameter is not viewable."
                        if value.parameter.type == 'data':
                            try:
                                if action_param_extra:
                                    assert value.parameter.allow_extra_files_access, "Extra file content requested (%s), but allow_extra_files_access is False." % (action_param_extra)
                                    file_name = os.path.join(value.extra_files_path, action_param_extra)
                                else:
                                    file_name = value.file_name
                                content_length = os.path.getsize(file_name)
                                rval = open(file_name)
                            except OSError as e:
                                log.debug("Unable to access requested file in display application: %s", e)
                                return paste.httpexceptions.HTTPNotFound("This file is no longer available.")
                        else:
                            rval = str(value)
                            content_length = len(rval)
                        trans.response.set_content_type(value.mime_type(action_param_extra=action_param_extra))
                        trans.response.headers['Content-Length'] = content_length
                        return rval
                    elif app_action is None:
                        # redirect user to url generated by display link
                        # Fix for Safari caching display links, which can change if the underlying dataset has an attribute change, e.g. name, metadata, etc
                        trans.response.headers['Cache-Control'] = ['no-cache', 'max-age=0', 'no-store', 'must-revalidate']
                        return trans.response.send_redirect(display_link.display_url())
                    else:
                        msg.append(('Invalid action provided: %s' % app_action, 'error'))
                else:
                    if app_action is None:
                        if trans.history != data.history:
                            msg.append(('You must import this dataset into your current history before you can view it at the desired display application.', 'error'))
                        else:
                            refresh = True
                            msg.append(('Launching this display application required additional datasets to be generated, you can view the status of these jobs below. ', 'info'))
                            if not display_link.preparing_display():
                                display_link.prepare_display()
                            preparable_steps = display_link.get_prepare_steps()
                    else:
                        raise Exception('Attempted a view action (%s) on a non-ready display application' % app_action)
            return trans.fill_template_mako("dataset/display_application/display.mako",
                                            msg=msg,
                                            display_app=display_app,
                                            display_link=display_link,
                                            refresh=refresh,
                                            preparable_steps=preparable_steps)
        return trans.show_error_message('You do not have permission to view this dataset at an external display application.')

    def _delete(self, trans, dataset_id):
        message = None
        status = 'done'
        id = None
        try:
            id = self.decode_id(dataset_id)
            hda = trans.sa_session.query(self.app.model.HistoryDatasetAssociation).get(id)
            assert hda, 'Invalid HDA: %s' % id
            # Walk up parent datasets to find the containing history
            topmost_parent = hda
            while topmost_parent.parent:
                topmost_parent = topmost_parent.parent
            assert topmost_parent in trans.history.datasets, "Data does not belong to current history"
            # Mark deleted and cleanup
            hda.mark_deleted()
            hda.clear_associated_files()
            trans.log_event("Dataset id %s marked as deleted" % str(id))
            self.hda_manager.stop_creating_job(hda)
            trans.sa_session.flush()
        except Exception as e:
            msg = 'HDA deletion failed (encoded: %s, decoded: %s)' % (dataset_id, id)
            log.exception(msg + ': ' + str(e))
            trans.log_event(msg)
            message = 'Dataset deletion failed'
            status = 'error'
        return (message, status)

    def _undelete(self, trans, dataset_id):
        message = None
        status = 'done'
        id = None
        try:
            id = self.decode_id(dataset_id)
            history = trans.get_history()
            hda = trans.sa_session.query(self.app.model.HistoryDatasetAssociation).get(id)
            assert hda and hda.undeletable, 'Invalid HDA: %s' % id
            # Walk up parent datasets to find the containing history
            topmost_parent = hda
            while topmost_parent.parent:
                topmost_parent = topmost_parent.parent
            assert topmost_parent in history.datasets, "Data does not belong to current history"
            # Mark undeleted
            hda.mark_undeleted()
            trans.sa_session.flush()
            trans.log_event("Dataset id %s has been undeleted" % str(id))
        except Exception:
            msg = 'HDA undeletion failed (encoded: %s, decoded: %s)' % (dataset_id, id)
            log.exception(msg)
            trans.log_event(msg)
            message = 'Dataset undeletion failed'
            status = 'error'
        return (message, status)

    def _unhide(self, trans, dataset_id):
        try:
            id = self.decode_id(dataset_id)
        except:
            return False
        history = trans.get_history()
        hda = trans.sa_session.query(self.app.model.HistoryDatasetAssociation).get(id)
        if hda:
            # Walk up parent datasets to find the containing history
            topmost_parent = hda
            while topmost_parent.parent:
                topmost_parent = topmost_parent.parent
            assert topmost_parent in history.datasets, "Data does not belong to current history"
            # Mark undeleted
            hda.mark_unhidden()
            trans.sa_session.flush()
            trans.log_event("Dataset id %s has been unhidden" % str(id))
            return True
        return False

    def _purge(self, trans, dataset_id):
        message = None
        status = 'done'
        try:
            id = self.decode_id(dataset_id)
            user = trans.get_user()
            hda = trans.sa_session.query(self.app.model.HistoryDatasetAssociation).get(id)
            # Invalid HDA
            assert hda, 'Invalid history dataset ID'

            # Walk up parent datasets to find the containing history
            topmost_parent = hda
            while topmost_parent.parent:
                topmost_parent = topmost_parent.parent
            # If the user is anonymous, make sure the HDA is owned by the current session.
            if not user:
                current_history_id = trans.galaxy_session.current_history_id
                assert topmost_parent.history.id == current_history_id, 'Data does not belong to current user'
            # If the user is known, make sure the HDA is owned by the current user.
            else:
                assert topmost_parent.history.user == user, 'Data does not belong to current user'

            # Ensure HDA is deleted
            hda.deleted = True
            # HDA is purgeable
            # Decrease disk usage first
            if user:
                user.adjust_total_disk_usage(-hda.quota_amount(user))
            # Mark purged
            hda.purged = True
            trans.sa_session.add(hda)
            trans.log_event("HDA id %s has been purged" % hda.id)
            trans.sa_session.flush()
            # Don't delete anything if there are active HDAs or any LDDAs, even if
            # the LDDAs are deleted.  Let the cleanup scripts get it in the latter
            # case.
            if hda.dataset.user_can_purge:
                try:
                    hda.dataset.full_delete()
                    trans.log_event("Dataset id %s has been purged upon the the purge of HDA id %s" % (hda.dataset.id, hda.id))
                    trans.sa_session.add(hda.dataset)
                except:
                    log.exception('Unable to purge dataset (%s) on purge of HDA (%s):' % (hda.dataset.id, hda.id))
            trans.sa_session.flush()
        except Exception as exc:
            msg = 'HDA purge failed (encoded: %s, decoded: %s): %s' % (dataset_id, id, exc)
            log.exception(msg)
            trans.log_event(msg)
            message = 'Dataset removal from disk failed'
            status = 'error'
        return (message, status)

    @web.expose
    def delete(self, trans, dataset_id, filename, show_deleted_on_refresh=False):
        message, status = self._delete(trans, dataset_id)
        return trans.response.send_redirect(web.url_for(controller='root', action='history', show_deleted=show_deleted_on_refresh, message=message, status=status))

    @web.expose
    def delete_async(self, trans, dataset_id, filename):
        message, status = self._delete(trans, dataset_id)
        if status == 'done':
            return "OK"
        else:
            raise Exception(message)

    @web.expose
    def undelete(self, trans, dataset_id, filename):
        message, status = self._undelete(trans, dataset_id)
        return trans.response.send_redirect(web.url_for(controller='root', action='history', show_deleted=True, message=message, status=status))

    @web.expose
    def undelete_async(self, trans, dataset_id, filename):
        message, status = self._undelete(trans, dataset_id)
        if status == 'done':
            return "OK"
        else:
            raise Exception(message)

    @web.expose
    def unhide(self, trans, dataset_id, filename):
        if self._unhide(trans, dataset_id):
            return trans.response.send_redirect(web.url_for(controller='root', action='history', show_hidden=True))
        raise Exception("Error unhiding")

    @web.expose
    def purge(self, trans, dataset_id, filename, show_deleted_on_refresh=False):
        if trans.app.config.allow_user_dataset_purge:
            message, status = self._purge(trans, dataset_id)
        else:
            message = "Removal of datasets by users is not allowed in this Galaxy instance.  Please contact your Galaxy administrator."
            status = 'error'
        return trans.response.send_redirect(web.url_for(controller='root', action='history', show_deleted=show_deleted_on_refresh, message=message, status=status))

    @web.expose
    def purge_async(self, trans, dataset_id, filename):
        if trans.app.config.allow_user_dataset_purge:
            message, status = self._purge(trans, dataset_id)
        else:
            message = "Removal of datasets by users is not allowed in this Galaxy instance.  Please contact your Galaxy administrator."
            status = 'error'
        if status == 'done':
            return "OK"
        else:
            raise Exception(message)

    @web.expose
    def show_params(self, trans, dataset_id=None, from_noframe=None, **kwd):
        """
        Show the parameters used for the job associated with an HDA
        """
        try:
            hda = trans.sa_session.query(trans.app.model.HistoryDatasetAssociation).get(self.decode_id(dataset_id))
        except ValueError:
            hda = None
        if not hda:
            raise paste.httpexceptions.HTTPRequestRangeNotSatisfiable("Invalid reference dataset id: %s." % escape(str(dataset_id)))
        if not self._can_access_dataset(trans, hda):
            return trans.show_error_message("You are not allowed to access this dataset")

        # Get the associated job, if any. If this hda was copied from another,
        # we need to find the job that created the origial dataset association.
        params_objects = None
        job = None
        tool = None
        upgrade_messages = {}
        has_parameter_errors = False
        inherit_chain = hda.source_dataset_chain
        if inherit_chain:
            job_dataset_association = inherit_chain[-1][0]
        else:
            job_dataset_association = hda
        if job_dataset_association.creating_job_associations:
            job = job_dataset_association.creating_job_associations[0].job
            if job:
                # Get the tool object
                try:
                    # Load the tool
                    toolbox = self.get_toolbox()
                    tool = toolbox.get_tool(job.tool_id, job.tool_version)
                    assert tool is not None, 'Requested tool has not been loaded.'
                    # Load parameter objects, if a parameter type has changed, it's possible for the value to no longer be valid
                    try:
                        params_objects = job.get_param_values(trans.app, ignore_errors=False)
                    except:
                        params_objects = job.get_param_values(trans.app, ignore_errors=True)
                        # use different param_objects in the following line, since we want to display original values as much as possible
                        upgrade_messages = tool.check_and_update_param_values(job.get_param_values(trans.app, ignore_errors=True),
                                                                              trans,
                                                                              update_values=False)
                        has_parameter_errors = True
                except:
                    pass
        if job is None:
            return trans.show_error_message("Job information is not available for this dataset.")
        # TODO: we should provide the basic values along with the objects, in order to better handle reporting of old values during upgrade
        return trans.fill_template("show_params.mako",
                                   inherit_chain=inherit_chain,
                                   history=trans.get_history(),
                                   hda=hda,
                                   job=job,
                                   tool=tool,
                                   params_objects=params_objects,
                                   upgrade_messages=upgrade_messages,
                                   has_parameter_errors=has_parameter_errors)

    @web.expose
    def copy_datasets(self, trans, source_history=None, source_content_ids="", target_history_id=None, target_history_ids="", new_history_name="", do_copy=False, **kwd):
        user = trans.get_user()
        if source_history is not None:
            decoded_source_history_id = self.decode_id(source_history)
            history = self.history_manager.get_owned(decoded_source_history_id, trans.user, current_history=trans.history)
            current_history = trans.get_history()
        else:
            history = current_history = trans.get_history()
        refresh_frames = []
        if source_content_ids:
            if not isinstance(source_content_ids, list):
                source_content_ids = source_content_ids.split(",")
            encoded_dataset_collection_ids = [s[len("dataset_collection|"):] for s in source_content_ids if s.startswith("dataset_collection|")]
            encoded_dataset_ids = [s[len("dataset|"):] for s in source_content_ids if s.startswith("dataset|")]
            decoded_dataset_collection_ids = set(map(self.decode_id, encoded_dataset_collection_ids))
            decoded_dataset_ids = set(map(self.decode_id, encoded_dataset_ids))
        else:
            decoded_dataset_collection_ids = []
            decoded_dataset_ids = []
        if new_history_name:
            target_history_ids = []
        else:
            if target_history_id:
                target_history_ids = [self.decode_id(target_history_id)]
            elif target_history_ids:
                if not isinstance(target_history_ids, list):
                    target_history_ids = target_history_ids.split(",")
                target_history_ids = list(set([self.decode_id(h) for h in target_history_ids if h]))
            else:
                target_history_ids = []
        done_msg = error_msg = ""
        new_history = None
        if do_copy:
            invalid_contents = 0
            if not (decoded_dataset_ids or decoded_dataset_collection_ids) or not (target_history_ids or new_history_name):
                error_msg = "You must provide both source datasets and target histories. "
            else:
                if new_history_name:
                    new_history = trans.app.model.History()
                    new_history.name = new_history_name
                    new_history.user = user
                    trans.sa_session.add(new_history)
                    trans.sa_session.flush()
                    target_history_ids.append(new_history.id)
                if user:
                    target_histories = [hist for hist in map(trans.sa_session.query(trans.app.model.History).get, target_history_ids) if hist is not None and hist.user == user]
                else:
                    target_histories = [history]
                if len(target_histories) != len(target_history_ids):
                    error_msg = error_msg + "You do not have permission to add datasets to %i requested histories.  " % (len(target_history_ids) - len(target_histories))
                source_contents = map(trans.sa_session.query(trans.app.model.HistoryDatasetAssociation).get, decoded_dataset_ids)
                source_contents.extend(map(trans.sa_session.query(trans.app.model.HistoryDatasetCollectionAssociation).get, decoded_dataset_collection_ids))
                source_contents.sort(key=lambda content: content.hid)
                for content in source_contents:
                    if content is None:
                        error_msg = error_msg + "You tried to copy a dataset that does not exist. "
                        invalid_contents += 1
                    elif content.history != history:
                        error_msg = error_msg + "You tried to copy a dataset which is not in your current history. "
                        invalid_contents += 1
                    else:
                        for hist in target_histories:
                            if content.history_content_type == "dataset":
                                hist.add_dataset(content.copy(copy_children=True))
                            else:
                                copy_collected_datasets = True
                                copy_kwds = {}
                                if copy_collected_datasets:
                                    copy_kwds["element_destination"] = hist
                                hist.add_dataset_collection(content.copy(**copy_kwds))
                if current_history in target_histories:
                    refresh_frames = ['history']
                trans.sa_session.flush()
                hist_names_str = ", ".join(['<a href="%s" target="_top">%s</a>' %
                                            (url_for(controller="history", action="switch_to_history",
                                                     hist_id=trans.security.encode_id(hist.id)), escape(hist.name))
                                            for hist in target_histories])
                num_source = len(source_content_ids) - invalid_contents
                num_target = len(target_histories)
                done_msg = "%i %s copied to %i %s: %s." % (num_source, inflector.cond_plural(num_source, "dataset"), num_target, inflector.cond_plural(num_target, "history"), hist_names_str)
                trans.sa_session.refresh(history)
        source_contents = history.active_contents
        target_histories = [history]
        if user:
            target_histories = user.active_histories
        return trans.fill_template("/dataset/copy_view.mako",
                                   source_history=history,
                                   current_history=current_history,
                                   source_content_ids=source_content_ids,
                                   target_history_id=target_history_id,
                                   target_history_ids=target_history_ids,
                                   source_contents=source_contents,
                                   target_histories=target_histories,
                                   new_history_name=new_history_name,
                                   done_msg=done_msg,
                                   error_msg=error_msg,
                                   refresh_frames=refresh_frames)

    def _copy_datasets(self, trans, dataset_ids, target_histories, imported=False):
        """ Helper method for copying datasets. """
        user = trans.get_user()
        done_msg = error_msg = ""

        invalid_datasets = 0
        if not dataset_ids or not target_histories:
            error_msg = "You must provide both source datasets and target histories."
        else:
            # User must own target histories to copy datasets to them.
            for history in target_histories:
                if user != history.user:
                    error_msg = error_msg + "You do not have permission to add datasets to %i requested histories.  " % (len(target_histories))
            for dataset_id in dataset_ids:
                decoded_id = self.decode_id(dataset_id)
                data = self.hda_manager.get_accessible(decoded_id, trans.user)
                data = self.hda_manager.error_if_uploading(data)

                if data is None:
                    error_msg = error_msg + "You tried to copy a dataset that does not exist or that you do not have access to.  "
                    invalid_datasets += 1
                else:
                    for hist in target_histories:
                        dataset_copy = data.copy(copy_children=True)
                        if imported:
                            dataset_copy.name = "imported: " + dataset_copy.name
                        hist.add_dataset(dataset_copy)
            trans.sa_session.flush()
            num_datasets_copied = len(dataset_ids) - invalid_datasets
            done_msg = "%i dataset%s copied to %i histor%s." % \
                (num_datasets_copied, iff(num_datasets_copied == 1, "", "s"), len(target_histories), iff(len(target_histories) == 1, "y", "ies"))
            trans.sa_session.refresh(history)

        if error_msg != "":
            status = ERROR
            message = error_msg
        else:
            status = SUCCESS
            message = done_msg
        return status, message
