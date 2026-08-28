"""Small reaction-diffusion and Eikonal examples."""
from ugts_kc3.dynamics import fast_sweeping_eikonal, gray_scott_split_1d

u = [1.0] * 32
v = [0.0] * 32
for i in range(14, 18):
    u[i] = 0.5
    v[i] = 0.25
for _ in range(25):
    u, v = gray_scott_split_1d(u, v, dt=0.2, substeps=2)
print("gray_scott_u_center", [round(x, 6) for x in u[13:19]])
print("gray_scott_v_center", [round(x, 6) for x in v[13:19]])

arrival = fast_sweeping_eikonal([[1.0] * 7 for _ in range(7)], [(3, 3)], sweeps=6)
print("arrival_center_row", [round(x, 4) for x in arrival[3]])
