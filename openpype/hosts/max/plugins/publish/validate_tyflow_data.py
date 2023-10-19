import pyblish.api
from openpype.pipeline import PublishValidationError
from pymxs import runtime as rt


class ValidateTyFlowData(pyblish.api.InstancePlugin):
    """Validate that TyFlow plugins or
    relevant operators being set correctly."""

    order = pyblish.api.ValidatorOrder
    families = ["pointcloud", "tycache"]
    hosts = ["max"]
    label = "TyFlow Data"

    def process(self, instance):
        """
        Notes:
            1. Validate the container only include tyFlow objects
            2. Validate if tyFlow operator Export Particle exists

        """

        invalid_object = self.get_tyflow_object(instance)
        if invalid_object:
            self.log.error(f"Non tyFlow object found: {invalid_object}")

        invalid_operator = self.get_tyflow_operator(instance)
        if invalid_operator:
            self.log.error(
                "Operator 'Export Particles' not found in tyFlow editor.")
        if invalid_object or invalid_operator:
            raise PublishValidationError(
                "issues occurred",
                description="Container should only include tyFlow object\n "
                "and tyflow operator 'Export Particle' should be in \n"
                "the tyFlow editor")

    def get_tyflow_object(self, instance):
        """Get the nodes which are not tyFlow object(s)
        and editable mesh(es)

        Args:
            instance (pyblish.api.Instance): instance

        Returns:
            invalid(list): list of invalid nodes which are not
            tyFlow object(s) and editable mesh(es).
        """
        invalid = []
        container = instance.data["instance_node"]
        self.log.debug(f"Validating tyFlow container for {container}")

        selection_list = instance.data["members"]
        for sel in selection_list:
            sel_tmp = str(sel)
            if rt.ClassOf(sel) in [rt.tyFlow,
                                   rt.Editable_Mesh]:
                if "tyFlow" not in sel_tmp:
                    invalid.append(sel)
            else:
                invalid.append(sel)

        return invalid

    def get_tyflow_operator(self, instance):
        """Check if the Export Particle Operators in the node
        connections.

        Args:
            instance (str): instance node

        Returns:
            invalid(list): list of invalid nodes which do
            not consist of Export Particle Operators as parts
            of the node connections
        """
        invalid = []
        container = instance.data["instance_node"]
        self.log.debug(f"Validating tyFlow object for {container}")
        selection_list = instance.data["members"]
        bool_list = []
        for sel in selection_list:
            obj = sel.baseobject
            anim_names = rt.GetSubAnimNames(obj)
            for anim_name in anim_names:
                # get all the names of the related tyFlow nodes
                sub_anim = rt.GetSubAnim(obj, anim_name)
                # check if there is export particle operator
                boolean = rt.IsProperty(sub_anim, "Export_Particles")
                bool_list.append(str(boolean))
            # if the export_particles property is not there
            # it means there is not a "Export Particle" operator
            if "True" not in bool_list:
                invalid.append(sel)

        return invalid
