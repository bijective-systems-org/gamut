function n = append(dst, src)
%APPEND Adds the rows of src to dst in place and returns how many.
%   n = mestra.append(dst, src)
%   The rows get new ids continuing dst's; category tables merge by name.
%   Both files need the same declarations (bounds may differ), the same
%   mesh, and one geometry for a group member found in both.  Everything
%   is checked before the first row is written.
n = mestra_mex('append', char(dst), char(src));
end
