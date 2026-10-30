function cp = cylinderPressure(t, r, radius, gamma)
%CYLINDERPRESSURE Pressure coefficient of potential flow past a cylinder
%   with circulation gamma, free stream speed 1, as examples/_cylinder.py's
%   pressure.
uR = cos(t) .* (1 - radius^2 ./ r.^2);
uT = -sin(t) .* (1 + radius^2 ./ r.^2) + gamma ./ (2 * pi * r);
cp = 1 - (uR.^2 + uT.^2);
end
