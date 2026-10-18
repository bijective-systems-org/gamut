function writeCopy(src, dst)
%WRITECOPY Rewrites src as dst with the default layout (chunks and
%compression), as for a file another writer chunked finely.  The copy
%keeps the file's identity (file_id, created).
gamut_mex('write_copy', char(src), char(dst));
end
