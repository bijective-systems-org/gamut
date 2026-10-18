function v = field(s, name, default)
%FIELD s.(name) when present, else default.
if isstruct(s) && isfield(s, name)
    v = s.(name);
else
    v = default;
end
end
