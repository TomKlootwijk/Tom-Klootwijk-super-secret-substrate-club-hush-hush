"""Bounded impact and friction calculation."""
from ugts_kc3.constraints import normal_impact_impulse, clamp_friction_cone_2d

normal_impulse = normal_impact_impulse(relative_normal_velocity=-3.0, inverse_mass_sum=2.0, restitution=0.25)
friction_impulse = clamp_friction_cone_2d((2.0, -1.0), mu=0.5, normal_impulse=normal_impulse)
print("normal_impulse", normal_impulse)
print("friction_impulse", friction_impulse)
