"""Diffuse export policy for authored Sword/Shield facial albedo."""


def bake_sphere_reflection(material_name,flags):
    # Eye color maps already contain their authored pupil and highlight. An
    # object-space approximation of the view-dependent environment reflection
    # can saturate those small surfaces and erase the pupil entirely. Retain
    # their source albedo; body metal/ice still uses the portable sphere map.
    return bool(flags.get('SphereMapEnable')) and 'eye' not in material_name.casefold()
