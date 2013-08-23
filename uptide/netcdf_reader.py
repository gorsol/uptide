from scipy.io.netcdf import NetCDFFile
import math
import numpy

# any error generated by the NetCDFInterpolator object:
class NetCDFInterpolatorError(Exception): pass

# error caused by coordinates being out of range or inside land mask:
class CoordinateError(NetCDFInterpolatorError):
  def __init__(self, message, x, i, j):
    self.message = message
    self.x = x
    self.ij = i, j
  def __str__(self):
    return "at x, y={} indexed at i, j={}; {}".format(self.x, self.ij, self.message)

class Interpolator(object):
  def __init__(self, origin, delta, val, mask=None):
    self.origin = origin
    self.delta = delta
    self.val = val
    self.mask = mask
    # cache points that need to be extrapolated
    self.extrapolation_points = {}

  def set_mask(self, mask):
    self.mask = mask
    # changing the mask invalidates the extrapolation cache
    self.extrapolation_points ={}

  def find_extrapolation_points(self, x, i, j):
    if x in self.extrapolation_points:
      return self.extrapolation_points[x]

    # This should only happen infrequently, so warn user (till someone tells us this is too annoying)
    print "Need to extrapolate point coordinates ", x
    ijs = [(i-1, j+1), (i-1, j), (i, j-1), (i+1, j-1), (i+2, j), (i+2, j+1), (i+1, j+2), (i, j+2)] # Neighbouring points
    ijs += [(i-1, j-1), (i+2, j-1), (i+2, j+2), (i-1, j+2)] # Diagonal points

    extrap_points = []
    for a, b in ijs:
      try:
        if self.mask[a, b]:
          extrap_points.append((a, b))
      except IndexError:
        # if we go out of range, ignore this point
        pass

    if len(extrap_points) == 0:
      raise CoordinateError("Inside landmask - tried extrapolating but failed", x, i, j)

    self.extrapolation_points[x] = extrap_points

    return extrap_points


  def get_val(self, x, allow_extrapolation=False):
    xhat = (x[0]-self.origin[0])/self.delta[0]
    yhat = (x[1]-self.origin[1])/self.delta[1]
    i = math.floor(xhat)
    j = math.floor(yhat)
    # this is not catched as an IndexError below, because of wrapping of negative indices
    if i<0 or j<0:
      raise CoordinateError("Coordinate out of range", x, i, j)
    alpha = xhat % 1.0
    beta = yhat % 1.0
    try:
      if self.mask is not None:
        w00 = (1.0-alpha)*(1.0-beta)*self.mask[i,j]
        w10 = alpha*(1.0-beta)*self.mask[i+1,j]
        w01 = (1.0-alpha)*beta*self.mask[i,j+1]
        w11 = alpha*beta*self.mask[i+1,j+1]
        value = w00*self.val[...,i,j] + w10*self.val[...,i+1,j] + w01*self.val[...,i,j+1] + w11*self.val[...,i+1,j+1]
        sumw = w00+w10+w01+w11

        if sumw>0.0:
          value = value/sumw
        elif allow_extrapolation:
          extrap_points = self.find_extrapolation_points(x, i, j)
          value = sum([self.val[..., a, b] for a, b in extrap_points])/len(extrap_points)
        else:
          raise CoordinateError("Probing point inside land mask", x, i, j)

      else:
        value = ((1.0-beta)*((1.0-alpha)*self.val[...,i,j]+alpha*self.val[...,i+1,j])+
                  beta*((1.0-alpha)*self.val[...,i,j+1]+alpha*self.val[...,i+1,j+1]))
    except IndexError:
      raise CoordinateError("Coordinate out of range", x, i, j)
    return value
    
# note that a NetCDFInterpolator is *not* object an Interpolator object
# the latter is considered immutable, whereas the NetCDFInterpolator may
# change with set_ranges() and set_field() and will create a new Interpolator sub-object
# each time
class NetCDFInterpolator(object):
  """Implements an object to interpolate values from a NetCDF-stored data set.

  The NetCDF file should contain two coordinate fields, e.g. latitude and longitude. Each of those two coordinates
  is assumed to be aligned with one dimension of the logical 2D grid and should be equi-distant. 
  To open the NetCDFInterpolator object:

    nci = NetCDFInterpolator('foo.nc', ('nx', 'ny'), ('longitude', latitude'))

  Here 'nx' and 'ny' refer to the names of the dimensions of the logical 2D grid and 'longitude' and 'latitude' to the 
  names of the coordinate fields. The order of the two tuple-arguments should agree (e.g. here 'longitude' increases in the 'nx'
  and 'latitude' in the 'ny' direction) and correspond to the order of the field that is to be interpolated. This order 
  can be obtained by using the ncdump program of the standard NetCDF utils:
    
    $ ncdump -h foo.nc
    netcdf foo {
      dimensions:
        nx = 20 ;
        ny = 10 ;
        variables:
        double z(nx, ny) ;
        double mask(nx, ny) ;
        double longitude(nx) ;
        double latitude(ny) ;
    }

  The coordinate fields may be stored as 1d or 2d fields (although only two values will actually be read to determine the 
  origin and step size). To indicate the field to be interpolated:

    nci.set_field('z')

  To interpolate this field in any arbitrary point:

    nci.get_val((-3.0, 58.5))

  The order of the coordinates should again correspond to the way the field is stored. If many interpolations are done 
  within a sub-domain of the area covered by the NetCDF, it may be much more efficient to indicate the range of coordinates
  with:

     nci.set_ranges(((-4.0,-2.0),(58.0,59.0)))

  This will load all values within the indicated range (here -4.0<longitude<-2.0 and 58.0<latitude<59.0) in memory.
  A land-mask can be provided to avoid interpolating from undefined land-values. The mask field should be 0.0 in land points
  and 1.0 at sea.

     nci.set_mask('mask')

  Alternatively, a mask can be defined from a fill value that has been used to indicate undefined land-points. The field name
  (not necessarily the same as the interpolated field) and fill value should be provided:

     nci.set_mask_from_fill_value('z', -9999.)

  It is allowed to switch between different fields using multiple calls of set_field(). The mask and ranges will be retained. It is
  however not allowed to call set_mask() or set_ranges() more than once. Finally, the case where the coordinate fields (and optionally
  the mask field) is stored in a different file than the one containing the field values to be interpolated, the following syntax
  is provided:

    nci1 = NetCDFInterpolator('grid.nc', ('nx', 'ny'), ('longitude', latitude'))
    nci1.set_mask('mask')
    nci2 = NetCDFInterpolator('values.nc', nci1)
    nci2.set_field('temperature')
    nci2.get_val(...)

  Here, the coordinate information of nci, including the mask and ranges if set, are copied and used in nci2.

  """
  def __init__(self, filename, *args, **kwargs):
    self.nc = NetCDFFile(filename)

    if len(args)==1:

      # we copy the grid information of another netcdf interpolator

      nci = args[0]
      self.shape = nci.shape
      self.origin = nci.origin
      self.delta = nci.delta
      self.iranges = nci.iranges
      self.mask = nci.mask

    elif len(args)==2:

      dimensions = args[0]
      coordinate_fields = args[1]

      self.shape = []
      self.origin = []
      self.delta = []

      for dimension,field_name in zip(dimensions, coordinate_fields):
        self.shape.append(self.nc.dimensions[dimension])
        val = self.nc.variables[field_name]
        if len(val.shape)==1:
          self.origin.append(val[0])
          self.delta.append((val[-1]-self.origin[-1])/(self.shape[-1]-1))
        elif len(val.shape)==2:
          self.origin.append(val[0,0])
          self.delta.append((val[-1,-1]-self.origin[-1])/(self.shape[-1]-1))
        else:
          raise NetCDFInterpolatorError("Unrecognized shape of coordinate field")

      self.iranges = None
      self.mask = None

    self.interpolator = None

    if "ranges" in kwargs:
      ranges = kwargs("ranges")
      self.set_ranges(ranges)

  def set_ranges(self, ranges):
    """Set the range of the coordinates. All the values of points located within this range are read from file at once.
    This may be more efficient if many interpolations are done within this domain."""
    if self.iranges is not None:
      # this could probably be fixed, but requires thought and testing:
      raise NetCDFInterpolatorError("set_ranges() should only be called once!")

    self.iranges = []
    origin_new = []
    shape_new = []
    for xlimits,xmin,xshape,deltax in zip(ranges,self.origin,self.shape,self.delta):
      # compute the index range imin:imax
      # for the min, take one off (i.e. add an extra row column) to avoid rounding issues:
      imin = max( int((xlimits[0]-xmin)/deltax)-1, 0 )
      # for the max, we add 3 because:
      # 1) we're rounding off first
      # 2) add one extra for rounding off issues
      # 3) python imin:imax range means up to and *excluding* imax
      # Example: xmin=0.0,deltax=1.0,xlimits[1]=3.7 -> imax=6 
      # (which is one too many, but nearing 3.999 we may get into a situation where we have to interpolate between 4 and 5)
      imax = min( int((xlimits[1]-xmin)/deltax)+3, xshape)
      if imin>=imax:
        raise NetCDFInterpolatorError("Provided ranges outside netCDF range")
      self.iranges.append((imin,imax))
      origin_new.append(xmin+imin*deltax)
      shape_new.append(imax-imin)

    self.origin = origin_new
    self.shape = shape_new

    if self.mask is not None:
      ir = self.iranges
      self.mask = self.mask[ir[0][0]:ir[0][1],ir[1][0]:ir[1][1]]
    if self.interpolator is not None:
      ir = self.iranges
      self.val = self.val[...,ir[0][0]:ir[0][1],ir[1][0]:ir[1][1]]
      self.interpolator = Interpolator(self.origin, self.delta, self.val, self.mask)

  def set_mask(self, field_name):
    """Sets a land mask from a mask field. This field should have a value of 0.0 for land points and 1.0 for the sea"""
    if self.iranges is None:
      self.mask = self.nc.variables[field_name]
    else:
      ir = self.iranges
      self.mask = self.nc.variables[field_name][ir[0][0]:ir[0][1],ir[1][0]:ir[1][1]]
    if self.interpolator is not None:
      self.interpolator.set_mask(self.mask)

  def set_mask_from_fill_value(self, field_name, fill_value):
    """Sets a land mask, where all points for which the supplied field equals the supplied fill value. The supplied field_name
    does not have to be the same as the field that is interpolated from, set with set_field()."""
    if self.iranges is None:
      val = self.nc.variables[field_name]
    else:
      ir = self.iranges
      val = self.nc.variables[field_name][...,ir[0][0]:ir[0][1],ir[1][0]:ir[1][1]]
    if len(val.shape)==3:
      val = val[0,...]
    elif len(val.shape)==2:
      val = val[:]
    else:
      raise NetCDFInterpolatorError("Field to extract mask from, should have 2 or 3 dimensions")
    self.mask = numpy.where(val==fill_value,0.,1.)
    if self.interpolator is not None:
      self.interpolator.set_mask(self.mask)

  def set_field(self, field_name):
    """Set the name of the field to be interpolated."""
    self.field_name = field_name
    if self.iranges is None:
      self.val = self.nc.variables[field_name]
    else:
      ir = self.iranges
      self.val = self.nc.variables[field_name][...,ir[0][0]:ir[0][1],ir[1][0]:ir[1][1]]
    self.interpolator = Interpolator(self.origin, self.delta, self.val, self.mask)


  def get_val(self, x, allow_extrapolation=False):
    """Interpolate the field chosen with set_field(). The order of the coordinates should correspond with the storage order in the file."""
    if not hasattr(self, "interpolator"):
      raise NetCDFInterpolatorError("Should call set_field() before calling get_val()!")
    return self.interpolator.get_val(x, allow_extrapolation)
