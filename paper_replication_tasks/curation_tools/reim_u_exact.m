function z = reim_u_exact(p, s, m)
## Reference exact solution for the fractional Laplacian test problem
## (-Delta)^s u = 1 on (-1,1)^2, u=0 on the boundary, per FEM2D_factional_demo.m.
  z = zeros(size(p,1), 1);
  for i = 1:2:m
    sinpix = sin(i * pi * 0.5 * (p(:,1)+1));
    for j = 1:2:m
      z = z + (0.25 * (i^2+j^2) * pi^2)^(-s) * 16/i/j/pi^2 .* sinpix .* sin(j * pi * 0.5 * (p(:,2)+1));
    end
  end
end
