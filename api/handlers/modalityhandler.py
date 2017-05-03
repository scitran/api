from ..web import base
from .. import config
from ..auth import require_login, require_superuser
from ..dao import containerstorage, APINotFoundException
# from ..validators import validate_data

log = config.log


class ModalityHandler(base.RequestHandler):

    def __init__(self, request=None, response=None):
        super(ModalityHandler, self).__init__(request, response)
        self.storage = containerstorage.ContainerStorage('modalities', use_object_id=False)

    @require_login
    def get(self, modality_name):
        return self.storage.get_container(modality_name)

    @require_login
    def get_all(self):
        return self.storage.get_all_el(None, None, None)

    @require_superuser
    def post(self):
        payload = self.request.json_body
        # Clean this up when validate_data method is fixed to use new schemas
        # POST unnecessary, used to avoid run-time modification of schema
        #validate_data(payload, 'modality.json', 'input', 'POST', optional=True)

        result = self.storage.create_el(payload)
        if result.acknowledged:
            return {'_id': result.inserted_id}
        else:
            self.abort(400, 'Modality not inserted')

    @require_superuser
    def put(self, modality_name):
        payload = self.request.json_body
        # Clean this up when validate_data method is fixed to use new schemas
        # POST unnecessary, used to avoid run-time modification of schema
        #validate_data(payload, 'modality.json', 'input', 'POST', optional=True)

        result = self.storage.update_el(modality_name, payload)
        if result.matched_count == 1:
            return {'modified': result.modified_count}
        else:
            raise APINotFoundException('Modality with name {} not found, modality not updated'.format(modality_name))

    @require_superuser
    def delete(self, modality_name):
        result = self.storage.delete_el(modality_name)
        if result.deleted_count == 1:
            return {'deleted': result.deleted_count}
        else:
            raise APINotFoundException('Modality with name {} not found, modality not deleted'.format(modality_name))

    @staticmethod
    def check_classification(modality_name, classification_map):
        """
        Given a modality name and a proposed classification map,
        ensure:
          - that a modality exists with that name and has a classification
            map
          - all keys in the classification_map exist in the
            `classifications` map on the modality object
          - all the values in the arrays in the classification_map
            exist in the modality's classifications map

        For example:
            Modality = {
                "_id" = "Example_modality",
                "classifications": {
                    "Example1": ["Blue", "Green"]
                    "Example2": ["one", "two"]
                }
            }

        Returns True:
            classification_map = {
                "Example1": ["Blue"],
                "custom":   ["anything"]
            }

        Returns False:
            classification_map = {
                "Example1": ["Red"], # "Red" is not allowed
                "Example2": ["one", "two"]
            }
        """
        try:
            modality = containerstorage.ContainerStorage('modalities', use_object_id=False).get_container(modality_name)
        except APINotFoundException:
            if classification_map.keys() == ['custom']:
                # for unknown modalities allow only list of custom values
                return True
            else:
                return False

        classifications = modality.get('classifications')
        if not classifications:
            return False

        for k,array in classification_map.iteritems():
            if k == 'custom':
                # any unique value is allowed in custom list
                continue
            possible_values = classifications.get(k, [])
            if not set(array).issubset(set(possible_values)):
                return False

        return True
