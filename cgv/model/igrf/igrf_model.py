﻿# -*- coding: utf-8 -*-
'''
 igrf_model.py

    from igrf_model import igrfModel
    print igrfModel(2010).geographic(0.0, 45.0, 30.0)

    igrf = igrfModel(2010)
    print igrf.geographic(250.0, 44.1, 33.2, potential=True)

    {'east': 1943.9152472275391, 'north': 22859.665493440312, 'up': -42555.406085806499,
    '_': {'units': 'nanoTesla', 'name': 'IGRF magnetic field model', 'coordinates': 'geographic (ENU)'},
    'V': -129197189900.56564}


    26-10-2014 bjackel@ucalgary.ca

    To do:
        *provide declination/inclination etc
        *trace along field line

'''
# https://www.ngdc.noaa.gov/IAGA/vmod/igrf11coeffs.txt
# http://hanspeterschaub.info/Papers/UnderGradStudents/MagneticField.pdf

#!! http://onlinelibrary.wiley.com/doi/10.1029/JA087iA04p02533/references
# !! http://onlinelibrary.wiley.com/doi/10.1029/RG010i002p00599/abstract

import numpy as np
#import numexpr as ne  # doesn't provide any speed gain
import scipy
import scipy.special as spFunc
import scipy.misc as spMisc
import time
import unittest


class igrfModel(object):
    """
    Spherical harmonic expansion of geomagnetic field.
    """
    
    # Note: variables defined outside __init__ are "class attributes"
    # that are the same for all instances of that class.  This is a good
    # way to share common information such as a table of all coefficients.

    # Each instance can then keep track of whatever subset they are using.

    dtor = np.double(np.pi)/180.0
    Re = np.double(6371.20e3)   ;# Earth radius in metres
    coefficients = {}  ;# all model coefficients (at end of this file)

    # WGS-84 geoid parameters
    #
    #  a= 6378.137      ;equatorial radius in km
    #  b= 6356.752      ;polar radius in km
    #  f= 1.0/298.25722    ;flattening of the spheroid, should be = (a-b)/a
    a2= 40680631.6e6   ;# a^2
    b2= 40408296.0e6   ;# b^2


    def __init__(self, year=None, verbose=0):
        self.verbose = verbose
        self.coefficients = self.read_coefficients()
        self.set_year(year)

    # coefficients = self.read_coefficients(coeff)  # at end of file after data
    # cache coefficients and preliminary calculations
    mm = np.arange(15)
    nn = np.arange(15)
    n2, m2 = np.meshgrid(mm,nn)
    schmidt_norm = np.sqrt((2.0-1*(m2==0)) * spMisc.factorial(n2-m2) / spMisc.factorial(n2+m2))  * (-1)**m2

    """ FIXME: allow arbitrary year """
    def set_year(self, year=None):
        if year is None:
            year = time.gmtime()[0]  ;# today
            if self.verbose: print("Using today's date: ",year)
#        year = np.array(year) #.astype(int)

        self.year = year
        yearlist = np.array( sorted(  self.coefficients.keys() ) ) #; print(year,yearlist)
        if year in yearlist:
            self.gcoeff = self.coefficients[year]['g']
            self.hcoeff = self.coefficients[year]['h']
        else:
            year = np.clip(year, np.min(yearlist), np.max(yearlist) )
            y0 = yearlist[yearlist<=year]
            y0 = np.max(y0) # ; y0 = yearlist[-2] if y0.size!=1 else np.max(y0)
            y1 = yearlist[yearlist>y0] ; y1 = yearlist[-1] if len(y1)==0 else np.min(y1)
#            y1 = np.min(y1) # ; y1 = yearlist[-1] if y1.size!=1 else np.min(y1)
            dy = 0.0 if (y1==y0) else (year-y0)/np.float(y1-y0)
            c0, c1 = self.coefficients[y0], self.coefficients[y1]
            self.gcoeff = c0['g'] + dy*( c1['g'] - c0['g'] )
            self.hcoeff = c0['h'] + dy*( c1['h'] - c0['h'] )

        self.gcoeff *= self.schmidt_norm
        self.hcoeff *= self.schmidt_norm
	#-------------------------------------------------------


    def _spherical0(self, radius, theta, phi, degree=13):
        """
        Reference implementation that looks like the mathematical equations.
        Very slow.
        """
        R = self.Re
        G, H = self.gcoeff, self.hcoeff
        P, dP = spFunc.lpmn(n=degree, m=degree, z=np.cos(theta))
        dP *= -1*np.sin(theta)  ;# from d/dz to d/dtheta

        V = Br = Btheta = Bphi = 0
        for n in range(0,degree+1):
            for m in range(0,n+1):
                V +=      (R/radius)**(n+1)         * ( G[m,n] * np.cos(m*phi) + H[m,n] * np.sin(m*phi) ) * P[m,n]
                Br +=     (R/radius)**(n+2) * (n+1) * ( G[m,n] * np.cos(m*phi) + H[m,n] * np.sin(m*phi) ) * P[m,n]
                Btheta += (R/radius)**(n+2)         * ( G[m,n] * np.cos(m*phi) + H[m,n] * np.sin(m*phi) ) * dP[m,n]
                Bphi +=   (R/radius)**(n+2)         * ( -G[m,n] * np.sin(m*phi) + H[m,n] * np.cos(m*phi) ) * P[m,n] * m

        return Br, -Btheta, -Bphi/np.sin(theta), V*R
	#-------------------------------------------------------


    def _spherical1(self, radius, theta, phi, degree=13):
        """ Reference implementation that removes loops: 11.8x faster"""
        degree=14
        R = self.Re
        G, H = self.gcoeff, self.hcoeff
        P, dP = spFunc.lpmn(n=degree, m=degree, z=np.cos(theta))
        dP *= -1*np.sin(theta)  ;# from d/dz to d/dtheta
        N, M = np.meshgrid( np.arange(degree+1), np.arange(degree+1) )

        V =  np.sum(     (R/radius)**(N+1) * ( G * np.cos(M*phi) + H * np.sin(M*phi) ) * P )
        Br = np.sum(     (R/radius)**(N+2) * (N+1) * ( G * np.cos(M*phi) + H * np.sin(M*phi) ) * P )
        Btheta = np.sum( (R/radius)**(N+2) * ( G * np.cos(M*phi) + H * np.sin(M*phi) ) * dP )
        Bphi = np.sum(   (R/radius)**(N+2)         * ( -G * np.sin(M*phi) + H * np.cos(M*phi) ) * P * M )

        return Br, -Btheta, -Bphi/np.sin(theta), V*R
	#-------------------------------------------------------


    def _spherical2(self, radius, theta, phi, degree=13):
        """ Rearrange and refactor:  1.85x faster"""
        degree=14
#        G, H = self.gcoeff, self.hcoeff
        P, dP = spFunc.lpmn(n=degree, m=degree, z=np.cos(theta))  ;#  12 us
        dP *= -1*np.sin(theta)  ;# from d/dz to d/dtheta
        N, M = np.meshgrid( np.arange(degree+1)*1.0, np.arange(degree+1)*1.0 ) ;# 34 us
        tmp = M*phi
        Cphi, Sphi = np.cos(tmp) , np.sin(tmp)  # 16us
        Rr = self.Re/radius  ;  RrN2 = Rr**(N+2)  ;# 20us, could shave off 5us by doing exponential of vector, then broadcasting

        P *= RrN2
        Bphi = np.sum( ( -self.gcoeff * Sphi + self.hcoeff * Cphi ) * P * M )
        tmp =  self.gcoeff * Cphi + self.hcoeff * Sphi
        Btheta = np.sum( RrN2 * tmp * dP )
        tmp *= P
        Br = np.sum( (N+1) * tmp )
        V =  np.sum( 1.0 / Rr * tmp)

        return Br, -Btheta, -Bphi/np.sin(theta), V*self.Re
	#-------------------------------------------------------


    def _spherical3(self, radius, theta, phi, degree=13):
        """ Reference implementation that only calculates non-zero half of the
        triangular matrices.  Net benefit is zero: less math but more indexing.
        """
        degree=14
        G, H = self.gcoeff, self.hcoeff
        W = ((G!=0)|(H!=0))   ;# using np.where() takes 30 us longer
        G, H = G[W], H[W]
        P, dP = spFunc.lpmn(n=degree, m=degree, z=np.cos(theta))  ;#  12 us
        P, dP = P[W], dP[W]
        dP *= -1*np.sin(theta)  ;# from d/dz to d/dtheta
        N, M = np.meshgrid( np.arange(degree+1)*1.0, np.arange(degree+1)*1.0 ) ;# 34 us
        N, M = N[W], M[W]
        tmp = M*phi
        Cphi, Sphi = np.cos(tmp) , np.sin(tmp)  # 16us
        Rr = self.Re/radius  ;  RrN2 = Rr**(N+2)  ;# 20us, could shave off 5us by doing exponential of vector, then broadcasting

        P *= RrN2
        Bphi = np.sum( ( -G * Sphi + H * Cphi ) * P * M )
        tmp =  G * Cphi + H * Sphi
        Btheta = np.sum( RrN2 * tmp * dP )
        tmp *= P
        Br = np.sum( (N+1) * tmp )
        V =  np.sum( 1.0 / Rr * tmp)

        return Br, -Btheta, -Bphi/np.sin(theta), V*self.Re
	#-------------------------------------------------------


    def spherical(self, r=None, theta=None, phi=None, degree=14, potential=False, metadata=True, **kwargs):
        """
        IGRF model magnetic field vector expressed in spherical coordinates:
            radius from center of the earth [metres]
            colatitude from North pole [degrees]
            longitude from Greenwich [degrees] east
        """
        """
        Core calculation.  Express inner sum as matrix multiplication np.dot()
        to be nearly 1.5x faster than np.sum() based approach
        """
        # this version takes 100us - my IDL code takes 120us for all 3 components

        theta = np.clip(theta, 1.0e-6, np.pi-1.0e-6)   # avoid singularity at poles
        field = {}   ;# returning a collection of components is faster than forming an array

        # Use scipy library routine to do all the hard work of calculating
        # an array of Legendre polynomials and their derivatives.
        #
        Pmn, dPmn = spFunc.lpmn( n=degree, m=degree, z=np.cos(theta) )
        dPmn *= -1*np.sin(theta)  ;# from d/dz to d/dtheta
        # need to schmidt normalize, but more efficient to do once on coefficients
        #Pmn *= schmidt_norm  # could pre-multiply coefficients
        #dPmn *= schmidt_norm  # could pre-multiply coefficients

        gg, hh = self.gcoeff[0:degree+1,0:degree+1], self.hcoeff[0:degree+1,0:degree+1]  # 5us
        Gmn, Hmn = gg * Pmn , hh * Pmn # 10 us

        nn, mm = self.nn[0:degree+1], self.mm[0:degree+1]  # 1us
        rradius = np.abs(self.Re/r) ; rfactor = rradius**(nn+2)  # 9us
        mmphi = mm*phi ; cphi, sphi = np.cos(mmphi) , np.sin(mmphi)  ;# 14us

        # sum over M by multiplying a matrix and column vector
        msum = Gmn.T.dot( cphi ) + Hmn.T.dot( sphi )    ;# 9 us

        if (potential): #!! fixme !!  optimize radius calculation?
            field.update(V = self.Re * msum.dot( rfactor / rradius ))  # 9us of 150us

        field.update( r = msum.dot( (nn+1)*rfactor ) )  ;# 11 us

        msum = -Gmn.T.dot( mm*sphi ) + Hmn.T.dot( mm*cphi )
        field.update( phi = -msum.dot( rfactor ) / np.sin(theta) )

#       Gmn, Hmn = gg * dPmn , hh * dPmn  ; msum = Gmn.T.dot( cphi ) + Hmn.T.dot( sphi )
        msum = (gg*dPmn).T.dot( cphi ) + (hh*dPmn).T.dot( sphi )  ;# not actually faster
        field.update( theta = -msum.dot( rfactor )  )

        result = {'field':field}
        if (metadata):
            result.update( {'position':{'r':r, 'theta':theta, 'phi':phi}} )
            result.update( {'_':{'name':'IGRF magnetic field model', 'units':'nanoTesla',  'year':self.year}} )

        return result
	#-------------------------------------------------------




    def geographic(self, height=None, latitude=None, longitude=None, metadata=True, potential=False, **kwargs):
        """
        IGRF model magnetic field vector expressed in geographic (geodetic)
        coordinates: local East, North, Up (ENU).  Input height in metres above
        mean sea level, latitude in degrees North, longitude in degrees East.
        """
#        # WGS-84
#        a2= 40680631.6e6   ;# a^2
#        b2= 40408296.0e6   ;# b^2
#
#        dtor = np.double(np.pi)/180.0
#        alpha= latitude*dtor      #;geodetic latitude in radians
#        phi= longitude*dtor       #;geodetic/geocentric longitude in radians
#        calpha= np.cos(alpha)  ;  salpha = np.sin(alpha)
#        N= a2 / np.sqrt( a2 * calpha**2 + b2 * salpha**2 )
#        betaa= np.arctan( (b2/a2*N+height)/(N+height) * (salpha/calpha) )   #;Geocentric Latitude
#        theta= np.pi/2.0 - betaa                                    #;Geocentric co-latitude
#        r= (N+height) * calpha / np.cos(betaa)  #;Distance from the centre of the earth, metres
#        psi = alpha-betaa

        coords = self.convert_coordinates(height=height, latitude=latitude, longitude=longitude, **kwargs)
        result = self.spherical(r=coords['r'], theta=coords['theta'], phi=coords['phi'], potential=potential)
        psi = coords.get('psi',0.0)
        north = -result['field']['theta'] * np.cos(psi) - result['field']['r'] * np.sin(psi)
        east = result['field']['phi']
        down = result['field']['theta'] * np.sin(psi) - result['field']['r'] * np.cos(psi)
        result['field'].update( dict( east=east, north=north, up=-down) )

        b = result['field']   #;  print q
        b = np.array( [ b['north'], b['east'], b['up'] ] )
        field = np.sqrt( b[0]**2 + b[1]**2 + b[2]**2 )
        horizontal = np.sqrt( b[0]**2 + b[1]**2 )
        declination = np.arctan2( b[1], b[0] ) / self.dtor
        inclination = np.arctan2( b[2], horizontal ) / self.dtor
        result['field'].update( {'inclination':inclination, 'declination':declination, 'horizontal':horizontal, 'field':field} )

        if (metadata):
            result['position'].update( {'height':height, 'latitude':latitude, 'longitude':longitude} )

        return result
        ########################################################################


    def cartesian(self, x=None, y=None, z=None, metadata=True, potential=False, **kwargs): #pass
#        r = np.sqrt( x*x + y*y + z*z)
#        theta = np.arccos( z/r )
#        phi = np.arctan2(y,x)
        coords = self.convert_coordinates(x=x, y=y, z=z, **kwargs)
        result = self.spherical(r=coords['r'], theta=coords['theta'], phi=coords['phi'], potential=potential)
#        result = self.spherical( r=r, theta=theta, phi=phi, metadata=metadata, potential=potential )
        bx = result['field']['r'] * np.sin( result['field']['theta'] ) * np.cos( result['field']['phi'] )
        by = result['field']['r'] * np.sin( result['field']['theta'] ) * np.sin( result['field']['phi'] )
        bz = result['field']['r'] * np.cos( result['field']['theta'] )
        result['field'].update( dict(x=bx, y=by, z=bz) )
        if metadata:
            result['position'].update( dict( x=x, y=y, z=z ) )
        return result
	#-------------------------------------------------------


    def fdi(self,**kwargs):
        coords = self.convert_coordinates(**kwargs)
        result = self.geographic(**coords)
        b = result['field']   #;  print q
        b = np.array( [ b['x'], b['y'], b['z'] ] )
        field = np.sqrt( b[0]**2 + b[1]**2 + b[2]**2 )
        horizontal = np.sqrt( b[0]**2 + b[1]**2 )
        declination = np.arctan2( b[1], b[0] ) / self.dtor
        inclination = np.arctan2( b[2], horizontal ) / self.dtor
        result['field'].update( {'inclination':inclination, 'declination':declination, 'horizontal':horizontal, 'field':field} )
	#-------------------------------------------------------


    def convert_coordinates(self, spherical=True, cartesian=False, geographic=False, **kwargs):
#        print kwargs
        spher = [kwargs.pop(name,None) for name in ['r','theta','phi'] ]
        cart = [kwargs.pop(name,None) for name in ['x','y','z'] ]
        geog = [kwargs.pop(name,None) for name in ['height','latitude','longitude'] ]
        err = kwargs.keys()  # complain
        result = {}

        if (spherical):
            if not np.any([v is None for v in cart]):
                r = np.sqrt( cart[0]**2 + cart[1]**2 + cart[2]**2 )
                theta = np.arccos( cart[2] / r )
                phi = np.arctan2( cart[1] , cart[0] )
            elif not np.any([v is None for v in geog]):
                alpha= geog[1] * self.dtor      #;geodetic latitude in radians
                phi= geog[2] * self.dtor       #;geodetic/geocentric longitude in radians
                calpha= np.cos(alpha)  ;  salpha = np.sin(alpha)
                N= self.a2 / np.sqrt( self.a2 * calpha**2 + self.b2 * salpha**2 )
                betaa= np.arctan( (self.b2/self.a2*N+geog[0])/(N+geog[0]) * (salpha/calpha) )   #;Geocentric Latitude
                theta= np.pi/2.0 - betaa                                    #;Geocentric co-latitude
                r= (N+geog[0]) * calpha / np.cos(betaa)  #;Distance from the centre of the earth, metres
                result.update( {'psi': alpha - betaa})  ;# required for inverse
            elif np.any([v is None for v in spher]):
                print 'Error- unable to calculate spherical coordinates '
                print spher, cart, geog
                r = theta = phi = 0.0
            else: r, theta, phi = spher
            result.update({'r':r, 'theta':theta, 'phi':phi})

        if (cartesian):
            x = spher[0] * np.sin( spher[1] ) * np.cos( spher[2] )
            y = spher[0] * np.sin( spher[1] ) * np.sin( spher[2] )
            z = spher[0] * np.cos( spher[1] )
            result.update({'x':x, 'y':y, 'z':z})

        #if (geographic):
        #    x = spher[0] * np.sin( spher[1] ) * np.cos( spher[2] )
        #    y = spher[0] * np.sin( spher[1] ) * np.sin( spher[2] )
        #    z = spher[0] * np.cos( spher[1] )
        #    result.update({'x':x, 'y':y, 'z':z})

        return result
        #######################################################################


#  Approximate geoid as ellipsoid using WGS-84 reference model.
#
#  a= 6378.137      ;equatorial radius in km
#  b= 6356.752      ;polar radius in km
#  f= 1.0/298.25722    ;flattening of the spheroid, should be = (a-b)/a

    #def geoid(self, height=0.0, latitude=np.pi/2.0, longitude=2*np.pi):
    #    calpha= np.cos(alpha)  ;  salpha = np.sin(alpha)
    #    N= a2 / np.sqrt( a2 * calpha**2 + b2 * salpha**2 )
    #    betaa= np.arctan( (b2/a2*N+height)/(N+height) * (salpha/calpha) )   #;Geocentric Latitude
    #    theta= np.pi/2.0 - betaa                                    #;Geocentric co-latitude
    #    r= (N+height) * calpha / np.cos(betaa)  #;Distance from the centre of the earth, metres


 #   def trace(height, latitude, longitude, terminate:{'height':900e3}): pass    # field-line tracer
 #   def AACGM(): pass
 #   def Hapgood_coefficients(): pass
 #   def EDFL(): pass

# %timeit Pnm0, dPnm0 = scipy.special.lpmn(n=11,m=11,z=0.1)
# 100000 loops, best of 3: 17.8 µs per loop
# 11x11=17.7us, 12x12=17.5, 13x13=17.8, 14x14=18.3, 15x15=18.6, 20x20=21us
# Conclusion: calculating Legendre polynomials and derivatives is fairly quick,
#             and does not depend strongly on matrix size.

################################################################################
# Store the coefficients here so that we don't have to keep track of two files.
#
# 26 October 2014 - https://www.ngdc.noaa.gov/IAGA/vmod/igrf11coeffs.txt
#
    coeff = '''
# 11th Generation International Geomagnetic Reference Field Schmidt semi-normalised spherical harmonic coefficients, degree n=1,13
# in units nanoTesla for IGRF and definitive DGRF main-field models (degree n=1,8 nanoTesla/year for secular variation (SV))
         IGRF   IGRF   IGRF   IGRF   IGRF   IGRF   IGRF   IGRF   IGRF   DGRF   DGRF   DGRF   DGRF   DGRF   DGRF   DGRF   DGRF   DGRF   DGRF   DGRF     DGRF      DGRF     IGRF    SV
g/h n m 1900.0 1905.0 1910.0 1915.0 1920.0 1925.0 1930.0 1935.0 1940.0 1945.0 1950.0 1955.0 1960.0 1965.0 1970.0 1975.0 1980.0 1985.0 1990.0 1995.0   2000.0    2005.0   2010.0 2010-15
g  1  0 -31543 -31464 -31354 -31212 -31060 -30926 -30805 -30715 -30654 -30594 -30554 -30500 -30421 -30334 -30220 -30100 -29992 -29873 -29775 -29692 -29619.4 -29554.63 -29496.5   11.4
g  1  1  -2298  -2298  -2297  -2306  -2317  -2318  -2316  -2306  -2292  -2285  -2250  -2215  -2169  -2119  -2068  -2013  -1956  -1905  -1848  -1784  -1728.2  -1669.05  -1585.9   16.7
h  1  1   5922   5909   5898   5875   5845   5817   5808   5812   5821   5810   5815   5820   5791   5776   5737   5675   5604   5500   5406   5306   5186.1   5077.99   4945.1  -28.8
g  2  0   -677   -728   -769   -802   -839   -893   -951  -1018  -1106  -1244  -1341  -1440  -1555  -1662  -1781  -1902  -1997  -2072  -2131  -2200  -2267.7  -2337.24  -2396.6  -11.3
g  2  1   2905   2928   2948   2956   2959   2969   2980   2984   2981   2990   2998   3003   3002   2997   3000   3010   3027   3044   3059   3070   3068.4   3047.69   3026.0   -3.9
h  2  1  -1061  -1086  -1128  -1191  -1259  -1334  -1424  -1520  -1614  -1702  -1810  -1898  -1967  -2016  -2047  -2067  -2129  -2197  -2279  -2366  -2481.6  -2594.50  -2707.7  -23.0
g  2  2    924   1041   1176   1309   1407   1471   1517   1550   1566   1578   1576   1581   1590   1594   1611   1632   1663   1687   1686   1681   1670.9   1657.76   1668.6    2.7
h  2  2   1121   1065   1000    917    823    728    644    586    528    477    381    291    206    114     25    -68   -200   -306   -373   -413   -458.0   -515.43   -575.4  -12.9
g  3  0   1022   1037   1058   1084   1111   1140   1172   1206   1240   1282   1297   1302   1302   1297   1287   1276   1281   1296   1314   1335   1339.6   1336.30   1339.7    1.3
g  3  1  -1469  -1494  -1524  -1559  -1600  -1645  -1692  -1740  -1790  -1834  -1889  -1944  -1992  -2038  -2091  -2144  -2180  -2208  -2239  -2267  -2288.0  -2305.83  -2326.3   -3.9
h  3  1   -330   -357   -389   -421   -445   -462   -480   -494   -499   -499   -476   -462   -414   -404   -366   -333   -336   -310   -284   -262   -227.6   -198.86   -160.5    8.6
g  3  2   1256   1239   1223   1212   1205   1202   1205   1215   1232   1255   1274   1288   1289   1292   1278   1260   1251   1247   1248   1249   1252.1   1246.39   1231.7   -2.9
h  3  2      3     34     62     84    103    119    133    146    163    186    206    216    224    240    251    262    271    284    293    302    293.4    269.72    251.7   -2.9
g  3  3    572    635    705    778    839    881    907    918    916    913    896    882    878    856    838    830    833    829    802    759    714.5    672.51    634.2   -8.1
h  3  3    523    480    425    360    293    229    166    101     43    -11    -46    -83   -130   -165   -196   -223   -252   -297   -352   -427   -491.1   -524.72   -536.8   -2.1
g  4  0    876    880    884    887    889    891    896    903    914    944    954    958    957    957    952    946    938    936    939    940    932.3    920.55    912.6   -1.4
g  4  1    628    643    660    678    695    711    727    744    762    776    792    796    800    804    800    791    782    780    780    780    786.8    797.96    809.0    2.0
h  4  1    195    203    211    218    220    216    205    188    169    144    136    133    135    148    167    191    212    232    247    262    272.6    282.07    286.4    0.4
g  4  2    660    653    644    631    616    601    584    565    550    544    528    510    504    479    461    438    398    361    325    290    250.0    210.65    166.6   -8.9
h  4  2    -69    -77    -90   -109   -134   -163   -195   -226   -252   -276   -278   -274   -278   -269   -266   -265   -257   -249   -240   -236   -231.9   -225.23   -211.2    3.2
g  4  3   -361   -380   -400   -416   -424   -426   -422   -415   -405   -421   -408   -397   -394   -390   -395   -405   -419   -424   -423   -418   -403.0   -379.86   -357.1    4.4
h  4  3   -210   -201   -189   -173   -153   -130   -109    -90    -72    -55    -37    -23      3     13     26     39     53     69     84     97    119.8    145.15    164.4    3.6
g  4  4    134    146    160    178    199    217    234    249    265    304    303    290    269    252    234    216    199    170    141    122    111.3    100.00     89.7   -2.3
h  4  4    -75    -65    -55    -51    -57    -70    -90   -114   -141   -178   -210   -230   -255   -269   -279   -288   -297   -297   -299   -306   -303.8   -305.36   -309.2   -0.8
g  5  0   -184   -192   -201   -211   -221   -230   -237   -241   -241   -253   -240   -229   -222   -219   -216   -218   -218   -214   -214   -214   -218.8   -227.00   -231.1   -0.5
g  5  1    328    328    327    327    326    326    327    329    334    346    349    360    362    358    359    356    357    355    353    352    351.4    354.41    357.2    0.5
h  5  1   -210   -193   -172   -148   -122    -96    -72    -51    -33    -12      3     15     16     19     26     31     46     47     46     46     43.8     42.72     44.7    0.5
g  5  2    264    259    253    245    236    226    218    211    208    194    211    230    242    254    262    264    261    253    245    235    222.3    208.95    200.3   -1.5
h  5  2     53     56     57     58     58     58     60     64     71     95    103    110    125    128    139    148    150    150    154    165    171.9    180.25    188.9    1.5
g  5  3      5     -1     -9    -16    -23    -28    -32    -33    -33    -20    -20    -23    -26    -31    -42    -59    -74    -93   -109   -118   -130.4   -136.54   -141.2   -0.7
h  5  3    -33    -32    -33    -34    -38    -44    -53    -64    -75    -67    -87    -98   -117   -126   -139   -152   -151   -154   -153   -143   -133.1   -123.45   -118.1    0.9
g  5  4    -86    -93   -102   -111   -119   -125   -131   -136   -141   -142   -147   -152   -156   -157   -160   -159   -162   -164   -165   -166   -168.6   -168.05   -163.1    1.3
h  5  4   -124   -125   -126   -126   -125   -122   -118   -115   -113   -119   -122   -121   -114    -97    -91    -83    -78    -75    -69    -55    -39.3    -19.57      0.1    3.7
g  5  5    -16    -26    -38    -51    -62    -69    -74    -76    -76    -82    -76    -69    -63    -62    -56    -49    -48    -46    -36    -17    -12.9    -13.55     -7.7    1.4
h  5  5      3     11     21     32     43     51     58     64     69     82     80     78     81     81     83     88     92     95     97    107    106.3    103.85    100.9   -0.6
g  6  0     63     62     62     61     61     61     60     59     57     59     54     47     46     45     43     45     48     53     61     68     72.3     73.60     72.8   -0.3
g  6  1     61     60     58     57     55     54     53     53     54     57     57     57     58     61     64     66     66     65     65     67     68.2     69.56     68.6   -0.3
h  6  1     -9     -7     -5     -2      0      3      4      4      4      6     -1     -9    -10    -11    -12    -13    -15    -16    -16    -17    -17.4    -20.33    -20.8   -0.1
g  6  2    -11    -11    -11    -10    -10     -9     -9     -8     -7      6      4      3      1      8     15     28     42     51     59     68     74.2     76.74     76.0   -0.3
h  6  2     83     86     89     93     96     99    102    104    105    100     99     96     99    100    100     99     93     88     82     72     63.7     54.75     44.2   -2.1
g  6  3   -217   -221   -224   -228   -233   -238   -242   -246   -249   -246   -247   -247   -237   -228   -212   -198   -192   -185   -178   -170   -160.9   -151.34   -141.4    1.9
h  6  3      2      4      5      8     11     14     19     25     33     16     33     48     60     68     72     75     71     69     69     67     65.1     63.63     61.5   -0.4
g  6  4    -58    -57    -54    -51    -46    -40    -32    -25    -18    -25    -16     -8     -1      4      2      1      4      4      3     -1     -5.9    -14.58    -22.9   -1.6
h  6  4    -35    -32    -29    -26    -22    -18    -16    -15    -15     -9    -12    -16    -20    -32    -37    -41    -43    -48    -52    -58    -61.2    -63.53    -66.3   -0.5
g  6  5     59     57     54     49     44     39     32     25     18     21     12      7     -2      1      3      6     14     16     18     19     16.9     14.58     13.1   -0.2
h  6  5     36     32     28     23     18     13      8      4      0    -16    -12    -12    -11     -8     -6     -4     -2     -1      1      1      0.7      0.24      3.1    0.8
g  6  6    -90    -92    -95    -98   -101   -103   -104   -106   -107   -104   -105   -107   -113   -111   -112   -111   -108   -102    -96    -93    -90.4    -86.36    -77.9    1.8
h  6  6    -69    -67    -65    -62    -57    -52    -46    -40    -33    -39    -30    -24    -17     -7      1     11     17     21     24     36     43.8     50.94     54.9    0.5
g  7  0     70     70     71     72     73     73     74     74     74     70     65     65     67     75     72     71     72     74     77     77     79.0     79.88     80.4    0.2
g  7  1    -55    -54    -54    -54    -54    -54    -54    -53    -53    -40    -55    -56    -56    -57    -57    -56    -59    -62    -64    -72    -74.0    -74.46    -75.0   -0.1
h  7  1    -45    -46    -47    -48    -49    -50    -51    -52    -52    -45    -35    -50    -55    -61    -70    -77    -82    -83    -80    -69    -64.6    -61.14    -57.8    0.6
g  7  2      0      0      1      2      2      3      4      4      4      0      2      2      5      4      1      1      2      3      2      1      0.0     -1.65     -4.7   -0.6
h  7  2    -13    -14    -14    -14    -14    -14    -15    -17    -18    -18    -17    -24    -28    -27    -27    -26    -27    -27    -26    -25    -24.2    -22.57    -21.2    0.3
g  7  3     34     33     32     31     29     27     25     23     20      0      1     10     15     13     14     16     21     24     26     28     33.3     38.73     45.3    1.4
h  7  3    -10    -11    -12    -12    -13    -14    -14    -14    -14      2      0     -4     -6     -2     -4     -5     -5     -2      0      4      6.2      6.82      6.6   -0.2
g  7  4    -41    -41    -40    -38    -37    -35    -34    -33    -31    -29    -40    -32    -32    -26    -22    -14    -12     -6     -1      5      9.1     12.30     14.0    0.3
h  7  4     -1      0      1      2      4      5      6      7      7      6     10      8      7      6      8     10     16     20     21     24     24.0     25.35     24.9   -0.1
g  7  5    -21    -20    -19    -18    -16    -14    -12    -11     -9    -10     -7    -11     -7     -6     -2      0      1      4      5      4      6.9      9.37     10.4    0.1
h  7  5     28     28     28     28     28     29     29     29     29     28     36     28     23     26     23     22     18     17     17     17     14.8     10.93      7.0   -0.8
g  7  6     18     18     18     19     19     19     18     18     17     15      5      9     17     13     13     12     11     10      9      8      7.3      5.42      1.6   -0.8
h  7  6    -12    -12    -13    -15    -16    -17    -18    -19    -20    -17    -18    -20    -18    -23    -23    -23    -23    -23    -23    -24    -25.4    -26.32    -27.7   -0.3
g  7  7      6      6      6      6      6      6      6      6      5     29     19     18      8      1     -2     -5     -2      0      0     -2     -1.2      1.94      4.9    0.4
h  7  7    -22    -22    -22    -22    -22    -21    -20    -19    -19    -22    -16    -18    -17    -12    -11    -12    -10     -7     -4     -6     -5.8     -4.64     -3.4    0.2
g  8  0     11     11     11     11     11     11     11     11     11     13     22     11     15     13     14     14     18     21     23     25     24.4     24.80     24.3   -0.1
g  8  1      8      8      8      8      7      7      7      7      7      7     15      9      6      5      6      6      6      6      5      6      6.6      7.62      8.2    0.1
h  8  1      8      8      8      8      8      8      8      8      8     12      5     10     11      7      7      6      7      8     10     11     11.9     11.20     10.9    0.0
g  8  2     -4     -4     -4     -4     -3     -3     -3     -3     -3     -8     -4     -6     -4     -4     -2     -1      0      0     -1     -6     -9.2    -11.73    -14.5   -0.5
h  8  2    -14    -15    -15    -15    -15    -15    -15    -15    -14    -21    -22    -15    -14    -12    -15    -16    -18    -19    -19    -21    -21.5    -20.88    -20.0    0.2
g  8  3     -9     -9     -9     -9     -9     -9     -9     -9    -10     -5     -1    -14    -11    -14    -13    -12    -11    -11    -10     -9     -7.9     -6.88     -5.7    0.3
h  8  3      7      7      6      6      6      6      5      5      5    -12      0      5      7      9      6      4      4      5      6      8      8.5      9.83     11.9    0.5
g  8  4      1      1      1      2      2      2      2      1      1      9     11      6      2      0     -3     -8     -7     -9    -12    -14    -16.6    -18.11    -19.3   -0.3
h  8  4    -13    -13    -13    -13    -14    -14    -14    -15    -15     -7    -21    -23    -18    -16    -17    -19    -22    -23    -22    -23    -21.5    -19.71    -17.4    0.4
g  8  5      2      2      2      3      4      4      5      6      6      7     15     10     10      8      5      4      4      4      3      9      9.1     10.17     11.6    0.3
h  8  5      5      5      5      5      5      5      5      5      5      2     -8      3      4      4      6      6      9     11     12     15     15.5     16.22     16.7    0.1
g  8  6     -9     -8     -8     -8     -7     -7     -6     -6     -5    -10    -13     -7     -5     -1      0      0      3      4      4      6      7.0      9.36     10.9    0.2
h  8  6     16     16     16     16     17     17     18     18     19     18     17     23     23     24     21     18     16     14     12     11      8.9      7.61      7.1   -0.1
g  8  7      5      5      5      6      6      7      8      8      9      7      5      6     10     11     11     10      6      4      2     -5     -7.9    -11.25    -14.1   -0.5
h  8  7     -5     -5     -5     -5     -5     -5     -5     -5     -5      3     -4     -4      1     -3     -6    -10    -13    -15    -16    -16    -14.9    -12.76    -10.8    0.4
g  8  8      8      8      8      8      8      8      8      7      7      2     -1      9      8      4      3      1     -1     -4     -6     -7     -7.0     -4.87     -3.7    0.2
h  8  8    -18    -18    -18    -18    -19    -19    -19    -19    -19    -11    -17    -13    -20    -17    -16    -17    -15    -11    -10     -4     -2.1     -0.06      1.7    0.4
g  9  0      8      8      8      8      8      8      8      8      8      5      3      4      4      8      8      7      5      5      4      4      5.0      5.58      5.4    0.0
g  9  1     10     10     10     10     10     10     10     10     10    -21     -7      9      6     10     10     10     10     10      9      9      9.4      9.76      9.4    0.0
h  9  1    -20    -20    -20    -20    -20    -20    -20    -20    -21    -27    -24    -11    -18    -22    -21    -21    -21    -21    -20    -20    -19.7    -20.11    -20.5    0.0
g  9  2      1      1      1      1      1      1      1      1      1      1     -1     -4      0      2      2      2      1      1      1      3      3.0      3.58      3.4    0.0
h  9  2     14     14     14     14     14     14     14     15     15     17     19     12     12     15     16     16     16     15     15     15     13.4     12.69     11.6    0.0
g  9  3    -11    -11    -11    -11    -11    -11    -12    -12    -12    -11    -25     -5     -9    -13    -12    -12    -12    -12    -12    -10     -8.4     -6.94     -5.3    0.0
h  9  3      5      5      5      5      5      5      5      5      5     29     12      7      2      7      6      7      9      9     11     12     12.5     12.67     12.8    0.0
g  9  4     12     12     12     12     12     12     12     11     11      3     10      2      1     10     10     10      9      9      9      8      6.3      5.01      3.1    0.0
h  9  4     -3     -3     -3     -3     -3     -3     -3     -3     -3     -9      2      6      0     -4     -4     -4     -5     -6     -7     -6     -6.2     -6.72     -7.2    0.0
g  9  5      1      1      1      1      1      1      1      1      1     16      5      4      4     -1     -1     -1     -3     -3     -4     -8     -8.9    -10.76    -12.4    0.0
h  9  5     -2     -2     -2     -2     -2     -2     -2     -3     -3      4      2     -2     -3     -5     -5     -5     -6     -6     -7     -8     -8.4     -8.16     -7.4    0.0
g  9  6     -2     -2     -2     -2     -2     -2     -2     -2     -2     -3     -5      1     -1     -1      0     -1     -1     -1     -2     -1     -1.5     -1.25     -0.8    0.0
h  9  6      8      8      8      8      9      9      9      9      9      9      8     10      9     10     10     10      9      9      9      8      8.4      8.10      8.0    0.0
g  9  7      2      2      2      2      2      2      3      3      3     -4     -2      2     -2      5      3      4      7      7      7     10      9.3      8.76      8.4    0.0
h  9  7     10     10     10     10     10     10     10     11     11      6      8      7      8     10     11     11     10      9      8      5      3.8      2.92      2.2    0.0
g  9  8     -1      0      0      0      0      0      0      0      1     -3      3      2      3      1      1      1      2      1      1     -2     -4.3     -6.66     -8.4    0.0
h  9  8     -2     -2     -2     -2     -2     -2     -2     -2     -2      1    -11     -6      0     -4     -2     -3     -6     -7     -7     -8     -8.2     -7.73     -6.1    0.0
g  9  9     -1     -1     -1     -1     -1     -1     -2     -2     -2     -4      8      5     -1     -2     -1     -2     -5     -5     -6     -8     -8.2     -9.22    -10.1    0.0
h  9  9      2      2      2      2      2      2      2      2      2      8     -7      5      5      1      1      1      2      2      2      3      4.8      6.01      7.0    0.0
g 10  0     -3     -3     -3     -3     -3     -3     -3     -3     -3     -3     -8     -3      1     -2     -3     -3     -4     -4     -3     -3     -2.6     -2.17     -2.0    0.0
g 10  1     -4     -4     -4     -4     -4     -4     -4     -4     -4     11      4     -5     -3     -3     -3     -3     -4     -4     -4     -6     -6.0     -6.12     -6.3    0.0
h 10  1      2      2      2      2      2      2      2      2      2      5     13     -4      4      2      1      1      1      1      2      1      1.7      2.19      2.8    0.0
g 10  2      2      2      2      2      2      2      2      2      2      1     -1     -1      4      2      2      2      2      3      2      2      1.7      1.42      0.9    0.0
h 10  2      1      1      1      1      1      1      1      1      1      1     -2      0      1      1      1      1      0      0      1      0      0.0      0.10     -0.1    0.0
g 10  3     -5     -5     -5     -5     -5     -5     -5     -5     -5      2     13      2      0     -5     -5     -5     -5     -5     -5     -4     -3.1     -2.35     -1.1    0.0
h 10  3      2      2      2      2      2      2      2      2      2    -20    -10     -8      0      2      3      3      3      3      3      4      4.0      4.46      4.7    0.0
g 10  4     -2     -2     -2     -2     -2     -2     -2     -2     -2     -5     -4     -3     -1     -2     -1     -2     -2     -2     -2     -1     -0.5     -0.15     -0.2    0.0
h 10  4      6      6      6      6      6      6      6      6      6     -1      2     -2      2      6      4      4      6      6      6      5      4.9      4.76      4.4    0.0
g 10  5      6      6      6      6      6      6      6      6      6     -1      4      7      4      4      6      5      5      5      4      4      3.7      3.06      2.5    0.0
h 10  5     -4     -4     -4     -4     -4     -4     -4     -4     -4     -6     -3     -4     -5     -4     -4     -4     -4     -4     -4     -5     -5.9     -6.58     -7.2    0.0
g 10  6      4      4      4      4      4      4      4      4      4      8     12      4      6      4      4      4      3      3      3      2      1.0      0.29     -0.3    0.0
h 10  6      0      0      0      0      0      0      0      0      0      6      6      1      1      0      0     -1      0      0      0     -1     -1.2     -1.01     -1.0    0.0
g 10  7      0      0      0      0      0      0      0      0      0     -1      3     -2      1      0      1      1      1      1      1      2      2.0      2.06      2.2    0.0
h 10  7     -2     -2     -2     -2     -2     -2     -2     -1     -1     -4     -3     -3     -1     -2     -1     -1     -1     -1     -2     -2     -2.9     -3.47     -4.0    0.0
g 10  8      2      2      2      1      1      1      1      2      2     -3      2      6     -1      2      0      0      2      2      3      5      4.2      3.77      3.1    0.0
h 10  8      4      4      4      4      4      4      4      4      4     -2      6      7      6      3      3      3      4      4      3      1      0.2     -0.86     -2.0    0.0
g 10  9      2      2      2      2      3      3      3      3      3      5     10     -2      2      2      3      3      3      3      3      1      0.3     -0.21     -1.0    0.0
h 10  9      0      0      0      0      0      0      0      0      0      0     11     -1      0      0      1      1      0      0     -1     -2     -2.2     -2.31     -2.0    0.0
g 10 10      0      0      0      0      0      0      0      0      0     -2      3      0      0      0     -1     -1      0      0      0      0     -1.1     -2.09     -2.8    0.0
h 10 10     -6     -6     -6     -6     -6     -6     -6     -6     -6     -2      8     -3     -7     -6     -4     -5     -6     -6     -6     -7     -7.4     -7.93     -8.3    0.0
g 11  0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      2.7      2.95      3.0    0.0
g 11  1      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -1.7     -1.60     -1.5    0.0
h 11  1      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.1      0.26      0.1    0.0
g 11  2      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -1.9     -1.88     -2.1    0.0
h 11  2      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      1.3      1.44      1.7    0.0
g 11  3      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      1.5      1.44      1.6    0.0
h 11  3      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.9     -0.77     -0.6    0.0
g 11  4      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.1     -0.31     -0.5    0.0
h 11  4      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -2.6     -2.27     -1.8    0.0
g 11  5      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.1      0.29      0.5    0.0
h 11  5      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.9      0.90      0.9    0.0
g 11  6      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.7     -0.79     -0.8    0.0
h 11  6      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.7     -0.58     -0.4    0.0
g 11  7      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.7      0.53      0.4    0.0
h 11  7      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -2.8     -2.69     -2.5    0.0
g 11  8      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      1.7      1.80      1.8    0.0
h 11  8      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.9     -1.08     -1.3    0.0
g 11  9      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.1      0.16      0.2    0.0
h 11  9      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -1.2     -1.58     -2.1    0.0
g 11 10      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      1.2      0.96      0.8    0.0
h 11 10      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -1.9     -1.90     -1.9    0.0
g 11 11      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      4.0      3.99      3.8    0.0
h 11 11      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.9     -1.39     -1.8    0.0
g 12  0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -2.2     -2.15     -2.1    0.0
g 12  1      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.3     -0.29     -0.2    0.0
h 12  1      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.4     -0.55     -0.8    0.0
g 12  2      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.2      0.21      0.3    0.0
h 12  2      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.3      0.23      0.3    0.0
g 12  3      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.9      0.89      1.0    0.0
h 12  3      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      2.5      2.38      2.2    0.0
g 12  4      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.2     -0.38     -0.7    0.0
h 12  4      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -2.6     -2.63     -2.5    0.0
g 12  5      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.9      0.96      0.9    0.0
h 12  5      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.7      0.61      0.5    0.0
g 12  6      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.5     -0.30     -0.1    0.0
h 12  6      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.3      0.40      0.6    0.0
g 12  7      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.3      0.46      0.5    0.0
h 12  7      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.0      0.01      0.0    0.0
g 12  8      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.3     -0.35     -0.4    0.0
h 12  8      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.0      0.02      0.1    0.0
g 12  9      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.4     -0.36     -0.4    0.0
h 12  9      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.3      0.28      0.3    0.0
g 12 10      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.1      0.08      0.2    0.0
h 12 10      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.9     -0.87     -0.9    0.0
g 12 11      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.2     -0.49     -0.8    0.0
h 12 11      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.4     -0.34     -0.2    0.0
g 12 12      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.4     -0.08      0.0    0.0
h 12 12      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.8      0.88      0.8    0.0
g 13  0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.2     -0.16     -0.2    0.0
g 13  1      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.9     -0.88     -0.9    0.0
h 13  1      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.9     -0.76     -0.8    0.0
g 13  2      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.3      0.30      0.3    0.0
h 13  2      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.2      0.33      0.3    0.0
g 13  3      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.1      0.28      0.4    0.0
h 13  3      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      1.8      1.72      1.7    0.0
g 13  4      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.4     -0.43     -0.4    0.0
h 13  4      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.4     -0.54     -0.6    0.0
g 13  5      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      1.3      1.18      1.1    0.0
h 13  5      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -1.0     -1.07     -1.2    0.0
g 13  6      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.4     -0.37     -0.3    0.0
h 13  6      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.1     -0.04     -0.1    0.0
g 13  7      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.7      0.75      0.8    0.0
h 13  7      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.7      0.63      0.5    0.0
g 13  8      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.4     -0.26     -0.2    0.0
h 13  8      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.3      0.21      0.1    0.0
g 13  9      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.3      0.35      0.4    0.0
h 13  9      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.6      0.53      0.5    0.0
g 13 10      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.1     -0.05      0.0    0.0
h 13 10      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.3      0.38      0.4    0.0
g 13 11      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.4      0.41      0.4    0.0
h 13 11      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.2     -0.22     -0.2    0.0
g 13 12      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.0     -0.10     -0.3    0.0
h 13 12      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.5     -0.57     -0.5    0.0
g 13 13      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.1     -0.18     -0.3    0.0
h 13 13      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.9     -0.82     -0.8    0.0
    '''

# http://www.ngdc.noaa.gov/IAGA/vmod/igrf12coeffs.txt  January 05 2015
    coeff='''
# 12th Generation International Geomagnetic Reference Field Schmidt semi-normalised spherical harmonic coefficients, degree n=1,13
# in units nanoTesla for IGRF and definitive DGRF main-field models (degree n=1,8 nanoTesla/year for secular variation (SV))
c/s deg ord IGRF IGRF   IGRF   IGRF   IGRF   IGRF   IGRF   IGRF   IGRF   DGRF   DGRF   DGRF   DGRF   DGRF   DGRF   DGRF   DGRF   DGRF   DGRF   DGRF     DGRF      DGRF      DGRF     IGRF      SV
g/h n m 1900.0 1905.0 1910.0 1915.0 1920.0 1925.0 1930.0 1935.0 1940.0 1945.0 1950.0 1955.0 1960.0 1965.0 1970.0 1975.0 1980.0 1985.0 1990.0 1995.0   2000.0    2005.0    2010.0   2015.0 2015-20
g  1  0 -31543 -31464 -31354 -31212 -31060 -30926 -30805 -30715 -30654 -30594 -30554 -30500 -30421 -30334 -30220 -30100 -29992 -29873 -29775 -29692 -29619.4 -29554.63 -29496.57 -29442.0    10.3
g  1  1  -2298  -2298  -2297  -2306  -2317  -2318  -2316  -2306  -2292  -2285  -2250  -2215  -2169  -2119  -2068  -2013  -1956  -1905  -1848  -1784  -1728.2  -1669.05  -1586.42  -1501.0    18.1
h  1  1   5922   5909   5898   5875   5845   5817   5808   5812   5821   5810   5815   5820   5791   5776   5737   5675   5604   5500   5406   5306   5186.1   5077.99   4944.26   4797.1   -26.6
g  2  0   -677   -728   -769   -802   -839   -893   -951  -1018  -1106  -1244  -1341  -1440  -1555  -1662  -1781  -1902  -1997  -2072  -2131  -2200  -2267.7  -2337.24  -2396.06  -2445.1    -8.7
g  2  1   2905   2928   2948   2956   2959   2969   2980   2984   2981   2990   2998   3003   3002   2997   3000   3010   3027   3044   3059   3070   3068.4   3047.69   3026.34   3012.9    -3.3
h  2  1  -1061  -1086  -1128  -1191  -1259  -1334  -1424  -1520  -1614  -1702  -1810  -1898  -1967  -2016  -2047  -2067  -2129  -2197  -2279  -2366  -2481.6  -2594.50  -2708.54  -2845.6   -27.4
g  2  2    924   1041   1176   1309   1407   1471   1517   1550   1566   1578   1576   1581   1590   1594   1611   1632   1663   1687   1686   1681   1670.9   1657.76   1668.17   1676.7     2.1
h  2  2   1121   1065   1000    917    823    728    644    586    528    477    381    291    206    114     25    -68   -200   -306   -373   -413   -458.0   -515.43   -575.73   -641.9   -14.1
g  3  0   1022   1037   1058   1084   1111   1140   1172   1206   1240   1282   1297   1302   1302   1297   1287   1276   1281   1296   1314   1335   1339.6   1336.30   1339.85   1350.7     3.4
g  3  1  -1469  -1494  -1524  -1559  -1600  -1645  -1692  -1740  -1790  -1834  -1889  -1944  -1992  -2038  -2091  -2144  -2180  -2208  -2239  -2267  -2288.0  -2305.83  -2326.54  -2352.3    -5.5
h  3  1   -330   -357   -389   -421   -445   -462   -480   -494   -499   -499   -476   -462   -414   -404   -366   -333   -336   -310   -284   -262   -227.6   -198.86   -160.40   -115.3     8.2
g  3  2   1256   1239   1223   1212   1205   1202   1205   1215   1232   1255   1274   1288   1289   1292   1278   1260   1251   1247   1248   1249   1252.1   1246.39   1232.10   1225.6    -0.7
h  3  2      3     34     62     84    103    119    133    146    163    186    206    216    224    240    251    262    271    284    293    302    293.4    269.72    251.75    244.9    -0.4
g  3  3    572    635    705    778    839    881    907    918    916    913    896    882    878    856    838    830    833    829    802    759    714.5    672.51    633.73    582.0   -10.1
h  3  3    523    480    425    360    293    229    166    101     43    -11    -46    -83   -130   -165   -196   -223   -252   -297   -352   -427   -491.1   -524.72   -537.03   -538.4     1.8
g  4  0    876    880    884    887    889    891    896    903    914    944    954    958    957    957    952    946    938    936    939    940    932.3    920.55    912.66    907.6    -0.7
g  4  1    628    643    660    678    695    711    727    744    762    776    792    796    800    804    800    791    782    780    780    780    786.8    797.96    808.97    813.7     0.2
h  4  1    195    203    211    218    220    216    205    188    169    144    136    133    135    148    167    191    212    232    247    262    272.6    282.07    286.48    283.3    -1.3
g  4  2    660    653    644    631    616    601    584    565    550    544    528    510    504    479    461    438    398    361    325    290    250.0    210.65    166.58    120.4    -9.1
h  4  2    -69    -77    -90   -109   -134   -163   -195   -226   -252   -276   -278   -274   -278   -269   -266   -265   -257   -249   -240   -236   -231.9   -225.23   -211.03   -188.7     5.3
g  4  3   -361   -380   -400   -416   -424   -426   -422   -415   -405   -421   -408   -397   -394   -390   -395   -405   -419   -424   -423   -418   -403.0   -379.86   -356.83   -334.9     4.1
h  4  3   -210   -201   -189   -173   -153   -130   -109    -90    -72    -55    -37    -23      3     13     26     39     53     69     84     97    119.8    145.15    164.46    180.9     2.9
g  4  4    134    146    160    178    199    217    234    249    265    304    303    290    269    252    234    216    199    170    141    122    111.3    100.00     89.40     70.4    -4.3
h  4  4    -75    -65    -55    -51    -57    -70    -90   -114   -141   -178   -210   -230   -255   -269   -279   -288   -297   -297   -299   -306   -303.8   -305.36   -309.72   -329.5    -5.2
g  5  0   -184   -192   -201   -211   -221   -230   -237   -241   -241   -253   -240   -229   -222   -219   -216   -218   -218   -214   -214   -214   -218.8   -227.00   -230.87   -232.6    -0.2
g  5  1    328    328    327    327    326    326    327    329    334    346    349    360    362    358    359    356    357    355    353    352    351.4    354.41    357.29    360.1     0.5
h  5  1   -210   -193   -172   -148   -122    -96    -72    -51    -33    -12      3     15     16     19     26     31     46     47     46     46     43.8     42.72     44.58     47.3     0.6
g  5  2    264    259    253    245    236    226    218    211    208    194    211    230    242    254    262    264    261    253    245    235    222.3    208.95    200.26    192.4    -1.3
h  5  2     53     56     57     58     58     58     60     64     71     95    103    110    125    128    139    148    150    150    154    165    171.9    180.25    189.01    197.0     1.7
g  5  3      5     -1     -9    -16    -23    -28    -32    -33    -33    -20    -20    -23    -26    -31    -42    -59    -74    -93   -109   -118   -130.4   -136.54   -141.05   -140.9    -0.1
h  5  3    -33    -32    -33    -34    -38    -44    -53    -64    -75    -67    -87    -98   -117   -126   -139   -152   -151   -154   -153   -143   -133.1   -123.45   -118.06   -119.3    -1.2
g  5  4    -86    -93   -102   -111   -119   -125   -131   -136   -141   -142   -147   -152   -156   -157   -160   -159   -162   -164   -165   -166   -168.6   -168.05   -163.17   -157.5     1.4
h  5  4   -124   -125   -126   -126   -125   -122   -118   -115   -113   -119   -122   -121   -114    -97    -91    -83    -78    -75    -69    -55    -39.3    -19.57     -0.01     16.0     3.4
g  5  5    -16    -26    -38    -51    -62    -69    -74    -76    -76    -82    -76    -69    -63    -62    -56    -49    -48    -46    -36    -17    -12.9    -13.55     -8.03      4.1     3.9
h  5  5      3     11     21     32     43     51     58     64     69     82     80     78     81     81     83     88     92     95     97    107    106.3    103.85    101.04    100.2     0.0
g  6  0     63     62     62     61     61     61     60     59     57     59     54     47     46     45     43     45     48     53     61     68     72.3     73.60     72.78     70.0    -0.3
g  6  1     61     60     58     57     55     54     53     53     54     57     57     57     58     61     64     66     66     65     65     67     68.2     69.56     68.69     67.7    -0.1
h  6  1     -9     -7     -5     -2      0      3      4      4      4      6     -1     -9    -10    -11    -12    -13    -15    -16    -16    -17    -17.4    -20.33    -20.90    -20.8     0.0
g  6  2    -11    -11    -11    -10    -10     -9     -9     -8     -7      6      4      3      1      8     15     28     42     51     59     68     74.2     76.74     75.92     72.7    -0.7
h  6  2     83     86     89     93     96     99    102    104    105    100     99     96     99    100    100     99     93     88     82     72     63.7     54.75     44.18     33.2    -2.1
g  6  3   -217   -221   -224   -228   -233   -238   -242   -246   -249   -246   -247   -247   -237   -228   -212   -198   -192   -185   -178   -170   -160.9   -151.34   -141.40   -129.9     2.1
h  6  3      2      4      5      8     11     14     19     25     33     16     33     48     60     68     72     75     71     69     69     67     65.1     63.63     61.54     58.9    -0.7
g  6  4    -58    -57    -54    -51    -46    -40    -32    -25    -18    -25    -16     -8     -1      4      2      1      4      4      3     -1     -5.9    -14.58    -22.83    -28.9    -1.2
h  6  4    -35    -32    -29    -26    -22    -18    -16    -15    -15     -9    -12    -16    -20    -32    -37    -41    -43    -48    -52    -58    -61.2    -63.53    -66.26    -66.7     0.2
g  6  5     59     57     54     49     44     39     32     25     18     21     12      7     -2      1      3      6     14     16     18     19     16.9     14.58     13.10     13.2     0.3
h  6  5     36     32     28     23     18     13      8      4      0    -16    -12    -12    -11     -8     -6     -4     -2     -1      1      1      0.7      0.24      3.02      7.3     0.9
g  6  6    -90    -92    -95    -98   -101   -103   -104   -106   -107   -104   -105   -107   -113   -111   -112   -111   -108   -102    -96    -93    -90.4    -86.36    -78.09    -70.9     1.6
h  6  6    -69    -67    -65    -62    -57    -52    -46    -40    -33    -39    -30    -24    -17     -7      1     11     17     21     24     36     43.8     50.94     55.40     62.6     1.0
g  7  0     70     70     71     72     73     73     74     74     74     70     65     65     67     75     72     71     72     74     77     77     79.0     79.88     80.44     81.6     0.3
g  7  1    -55    -54    -54    -54    -54    -54    -54    -53    -53    -40    -55    -56    -56    -57    -57    -56    -59    -62    -64    -72    -74.0    -74.46    -75.00    -76.1    -0.2
h  7  1    -45    -46    -47    -48    -49    -50    -51    -52    -52    -45    -35    -50    -55    -61    -70    -77    -82    -83    -80    -69    -64.6    -61.14    -57.80    -54.1     0.8
g  7  2      0      0      1      2      2      3      4      4      4      0      2      2      5      4      1      1      2      3      2      1      0.0     -1.65     -4.55     -6.8    -0.5
h  7  2    -13    -14    -14    -14    -14    -14    -15    -17    -18    -18    -17    -24    -28    -27    -27    -26    -27    -27    -26    -25    -24.2    -22.57    -21.20    -19.5     0.4
g  7  3     34     33     32     31     29     27     25     23     20      0      1     10     15     13     14     16     21     24     26     28     33.3     38.73     45.24     51.8     1.3
h  7  3    -10    -11    -12    -12    -13    -14    -14    -14    -14      2      0     -4     -6     -2     -4     -5     -5     -2      0      4      6.2      6.82      6.54      5.7    -0.2
g  7  4    -41    -41    -40    -38    -37    -35    -34    -33    -31    -29    -40    -32    -32    -26    -22    -14    -12     -6     -1      5      9.1     12.30     14.00     15.0     0.1
h  7  4     -1      0      1      2      4      5      6      7      7      6     10      8      7      6      8     10     16     20     21     24     24.0     25.35     24.96     24.4    -0.3
g  7  5    -21    -20    -19    -18    -16    -14    -12    -11     -9    -10     -7    -11     -7     -6     -2      0      1      4      5      4      6.9      9.37     10.46      9.4    -0.6
h  7  5     28     28     28     28     28     29     29     29     29     28     36     28     23     26     23     22     18     17     17     17     14.8     10.93      7.03      3.4    -0.6
g  7  6     18     18     18     19     19     19     18     18     17     15      5      9     17     13     13     12     11     10      9      8      7.3      5.42      1.64     -2.8    -0.8
h  7  6    -12    -12    -13    -15    -16    -17    -18    -19    -20    -17    -18    -20    -18    -23    -23    -23    -23    -23    -23    -24    -25.4    -26.32    -27.61    -27.4     0.1
g  7  7      6      6      6      6      6      6      6      6      5     29     19     18      8      1     -2     -5     -2      0      0     -2     -1.2      1.94      4.92      6.8     0.2
h  7  7    -22    -22    -22    -22    -22    -21    -20    -19    -19    -22    -16    -18    -17    -12    -11    -12    -10     -7     -4     -6     -5.8     -4.64     -3.28     -2.2    -0.2
g  8  0     11     11     11     11     11     11     11     11     11     13     22     11     15     13     14     14     18     21     23     25     24.4     24.80     24.41     24.2     0.2
g  8  1      8      8      8      8      7      7      7      7      7      7     15      9      6      5      6      6      6      6      5      6      6.6      7.62      8.21      8.8     0.0
h  8  1      8      8      8      8      8      8      8      8      8     12      5     10     11      7      7      6      7      8     10     11     11.9     11.20     10.84     10.1    -0.3
g  8  2     -4     -4     -4     -4     -3     -3     -3     -3     -3     -8     -4     -6     -4     -4     -2     -1      0      0     -1     -6     -9.2    -11.73    -14.50    -16.9    -0.6
h  8  2    -14    -15    -15    -15    -15    -15    -15    -15    -14    -21    -22    -15    -14    -12    -15    -16    -18    -19    -19    -21    -21.5    -20.88    -20.03    -18.3     0.3
g  8  3     -9     -9     -9     -9     -9     -9     -9     -9    -10     -5     -1    -14    -11    -14    -13    -12    -11    -11    -10     -9     -7.9     -6.88     -5.59     -3.2     0.5
h  8  3      7      7      6      6      6      6      5      5      5    -12      0      5      7      9      6      4      4      5      6      8      8.5      9.83     11.83     13.3     0.1
g  8  4      1      1      1      2      2      2      2      1      1      9     11      6      2      0     -3     -8     -7     -9    -12    -14    -16.6    -18.11    -19.34    -20.6    -0.2
h  8  4    -13    -13    -13    -13    -14    -14    -14    -15    -15     -7    -21    -23    -18    -16    -17    -19    -22    -23    -22    -23    -21.5    -19.71    -17.41    -14.6     0.5
g  8  5      2      2      2      3      4      4      5      6      6      7     15     10     10      8      5      4      4      4      3      9      9.1     10.17     11.61     13.4     0.4
h  8  5      5      5      5      5      5      5      5      5      5      2     -8      3      4      4      6      6      9     11     12     15     15.5     16.22     16.71     16.2    -0.2
g  8  6     -9     -8     -8     -8     -7     -7     -6     -6     -5    -10    -13     -7     -5     -1      0      0      3      4      4      6      7.0      9.36     10.85     11.7     0.1
h  8  6     16     16     16     16     17     17     18     18     19     18     17     23     23     24     21     18     16     14     12     11      8.9      7.61      6.96      5.7    -0.3
g  8  7      5      5      5      6      6      7      8      8      9      7      5      6     10     11     11     10      6      4      2     -5     -7.9    -11.25    -14.05    -15.9    -0.4
h  8  7     -5     -5     -5     -5     -5     -5     -5     -5     -5      3     -4     -4      1     -3     -6    -10    -13    -15    -16    -16    -14.9    -12.76    -10.74     -9.1     0.3
g  8  8      8      8      8      8      8      8      8      7      7      2     -1      9      8      4      3      1     -1     -4     -6     -7     -7.0     -4.87     -3.54     -2.0     0.3
h  8  8    -18    -18    -18    -18    -19    -19    -19    -19    -19    -11    -17    -13    -20    -17    -16    -17    -15    -11    -10     -4     -2.1     -0.06      1.64      2.1     0.0
g  9  0      8      8      8      8      8      8      8      8      8      5      3      4      4      8      8      7      5      5      4      4      5.0      5.58      5.50      5.4     0.0
g  9  1     10     10     10     10     10     10     10     10     10    -21     -7      9      6     10     10     10     10     10      9      9      9.4      9.76      9.45      8.8     0.0
h  9  1    -20    -20    -20    -20    -20    -20    -20    -20    -21    -27    -24    -11    -18    -22    -21    -21    -21    -21    -20    -20    -19.7    -20.11    -20.54    -21.6     0.0
g  9  2      1      1      1      1      1      1      1      1      1      1     -1     -4      0      2      2      2      1      1      1      3      3.0      3.58      3.45      3.1     0.0
h  9  2     14     14     14     14     14     14     14     15     15     17     19     12     12     15     16     16     16     15     15     15     13.4     12.69     11.51     10.8     0.0
g  9  3    -11    -11    -11    -11    -11    -11    -12    -12    -12    -11    -25     -5     -9    -13    -12    -12    -12    -12    -12    -10     -8.4     -6.94     -5.27     -3.3     0.0
h  9  3      5      5      5      5      5      5      5      5      5     29     12      7      2      7      6      7      9      9     11     12     12.5     12.67     12.75     11.8     0.0
g  9  4     12     12     12     12     12     12     12     11     11      3     10      2      1     10     10     10      9      9      9      8      6.3      5.01      3.13      0.7     0.0
h  9  4     -3     -3     -3     -3     -3     -3     -3     -3     -3     -9      2      6      0     -4     -4     -4     -5     -6     -7     -6     -6.2     -6.72     -7.14     -6.8     0.0
g  9  5      1      1      1      1      1      1      1      1      1     16      5      4      4     -1     -1     -1     -3     -3     -4     -8     -8.9    -10.76    -12.38    -13.3     0.0
h  9  5     -2     -2     -2     -2     -2     -2     -2     -3     -3      4      2     -2     -3     -5     -5     -5     -6     -6     -7     -8     -8.4     -8.16     -7.42     -6.9     0.0
g  9  6     -2     -2     -2     -2     -2     -2     -2     -2     -2     -3     -5      1     -1     -1      0     -1     -1     -1     -2     -1     -1.5     -1.25     -0.76     -0.1     0.0
h  9  6      8      8      8      8      9      9      9      9      9      9      8     10      9     10     10     10      9      9      9      8      8.4      8.10      7.97      7.8     0.0
g  9  7      2      2      2      2      2      2      3      3      3     -4     -2      2     -2      5      3      4      7      7      7     10      9.3      8.76      8.43      8.7     0.0
h  9  7     10     10     10     10     10     10     10     11     11      6      8      7      8     10     11     11     10      9      8      5      3.8      2.92      2.14      1.0     0.0
g  9  8     -1      0      0      0      0      0      0      0      1     -3      3      2      3      1      1      1      2      1      1     -2     -4.3     -6.66     -8.42     -9.1     0.0
h  9  8     -2     -2     -2     -2     -2     -2     -2     -2     -2      1    -11     -6      0     -4     -2     -3     -6     -7     -7     -8     -8.2     -7.73     -6.08     -4.0     0.0
g  9  9     -1     -1     -1     -1     -1     -1     -2     -2     -2     -4      8      5     -1     -2     -1     -2     -5     -5     -6     -8     -8.2     -9.22    -10.08    -10.5     0.0
h  9  9      2      2      2      2      2      2      2      2      2      8     -7      5      5      1      1      1      2      2      2      3      4.8      6.01      7.01      8.4     0.0
g 10  0     -3     -3     -3     -3     -3     -3     -3     -3     -3     -3     -8     -3      1     -2     -3     -3     -4     -4     -3     -3     -2.6     -2.17     -1.94     -1.9     0.0
g 10  1     -4     -4     -4     -4     -4     -4     -4     -4     -4     11      4     -5     -3     -3     -3     -3     -4     -4     -4     -6     -6.0     -6.12     -6.24     -6.3     0.0
h 10  1      2      2      2      2      2      2      2      2      2      5     13     -4      4      2      1      1      1      1      2      1      1.7      2.19      2.73      3.2     0.0
g 10  2      2      2      2      2      2      2      2      2      2      1     -1     -1      4      2      2      2      2      3      2      2      1.7      1.42      0.89      0.1     0.0
h 10  2      1      1      1      1      1      1      1      1      1      1     -2      0      1      1      1      1      0      0      1      0      0.0      0.10     -0.10     -0.4     0.0
g 10  3     -5     -5     -5     -5     -5     -5     -5     -5     -5      2     13      2      0     -5     -5     -5     -5     -5     -5     -4     -3.1     -2.35     -1.07      0.5     0.0
h 10  3      2      2      2      2      2      2      2      2      2    -20    -10     -8      0      2      3      3      3      3      3      4      4.0      4.46      4.71      4.6     0.0
g 10  4     -2     -2     -2     -2     -2     -2     -2     -2     -2     -5     -4     -3     -1     -2     -1     -2     -2     -2     -2     -1     -0.5     -0.15     -0.16     -0.5     0.0
h 10  4      6      6      6      6      6      6      6      6      6     -1      2     -2      2      6      4      4      6      6      6      5      4.9      4.76      4.44      4.4     0.0
g 10  5      6      6      6      6      6      6      6      6      6     -1      4      7      4      4      6      5      5      5      4      4      3.7      3.06      2.45      1.8     0.0
h 10  5     -4     -4     -4     -4     -4     -4     -4     -4     -4     -6     -3     -4     -5     -4     -4     -4     -4     -4     -4     -5     -5.9     -6.58     -7.22     -7.9     0.0
g 10  6      4      4      4      4      4      4      4      4      4      8     12      4      6      4      4      4      3      3      3      2      1.0      0.29     -0.33     -0.7     0.0
h 10  6      0      0      0      0      0      0      0      0      0      6      6      1      1      0      0     -1      0      0      0     -1     -1.2     -1.01     -0.96     -0.6     0.0
g 10  7      0      0      0      0      0      0      0      0      0     -1      3     -2      1      0      1      1      1      1      1      2      2.0      2.06      2.13      2.1     0.0
h 10  7     -2     -2     -2     -2     -2     -2     -2     -1     -1     -4     -3     -3     -1     -2     -1     -1     -1     -1     -2     -2     -2.9     -3.47     -3.95     -4.2     0.0
g 10  8      2      2      2      1      1      1      1      2      2     -3      2      6     -1      2      0      0      2      2      3      5      4.2      3.77      3.09      2.4     0.0
h 10  8      4      4      4      4      4      4      4      4      4     -2      6      7      6      3      3      3      4      4      3      1      0.2     -0.86     -1.99     -2.8     0.0
g 10  9      2      2      2      2      3      3      3      3      3      5     10     -2      2      2      3      3      3      3      3      1      0.3     -0.21     -1.03     -1.8     0.0
h 10  9      0      0      0      0      0      0      0      0      0      0     11     -1      0      0      1      1      0      0     -1     -2     -2.2     -2.31     -1.97     -1.2     0.0
g 10 10      0      0      0      0      0      0      0      0      0     -2      3      0      0      0     -1     -1      0      0      0      0     -1.1     -2.09     -2.80     -3.6     0.0
h 10 10     -6     -6     -6     -6     -6     -6     -6     -6     -6     -2      8     -3     -7     -6     -4     -5     -6     -6     -6     -7     -7.4     -7.93     -8.31     -8.7     0.0
g 11  0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      2.7      2.95      3.05      3.1     0.0
g 11  1      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -1.7     -1.60     -1.48     -1.5     0.0
h 11  1      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.1      0.26      0.13     -0.1     0.0
g 11  2      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -1.9     -1.88     -2.03     -2.3     0.0
h 11  2      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      1.3      1.44      1.67      2.0     0.0
g 11  3      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      1.5      1.44      1.65      2.0     0.0
h 11  3      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.9     -0.77     -0.66     -0.7     0.0
g 11  4      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.1     -0.31     -0.51     -0.8     0.0
h 11  4      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -2.6     -2.27     -1.76     -1.1     0.0
g 11  5      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.1      0.29      0.54      0.6     0.0
h 11  5      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.9      0.90      0.85      0.8     0.0
g 11  6      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.7     -0.79     -0.79     -0.7     0.0
h 11  6      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.7     -0.58     -0.39     -0.2     0.0
g 11  7      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.7      0.53      0.37      0.2     0.0
h 11  7      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -2.8     -2.69     -2.51     -2.2     0.0
g 11  8      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      1.7      1.80      1.79      1.7     0.0
h 11  8      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.9     -1.08     -1.27     -1.4     0.0
g 11  9      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.1      0.16      0.12     -0.2     0.0
h 11  9      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -1.2     -1.58     -2.11     -2.5     0.0
g 11 10      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      1.2      0.96      0.75      0.4     0.0
h 11 10      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -1.9     -1.90     -1.94     -2.0     0.0
g 11 11      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      4.0      3.99      3.75      3.5     0.0
h 11 11      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.9     -1.39     -1.86     -2.4     0.0
g 12  0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -2.2     -2.15     -2.12     -1.9     0.0
g 12  1      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.3     -0.29     -0.21     -0.2     0.0
h 12  1      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.4     -0.55     -0.87     -1.1     0.0
g 12  2      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.2      0.21      0.30      0.4     0.0
h 12  2      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.3      0.23      0.27      0.4     0.0
g 12  3      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.9      0.89      1.04      1.2     0.0
h 12  3      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      2.5      2.38      2.13      1.9     0.0
g 12  4      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.2     -0.38     -0.63     -0.8     0.0
h 12  4      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -2.6     -2.63     -2.49     -2.2     0.0
g 12  5      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.9      0.96      0.95      0.9     0.0
h 12  5      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.7      0.61      0.49      0.3     0.0
g 12  6      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.5     -0.30     -0.11      0.1     0.0
h 12  6      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.3      0.40      0.59      0.7     0.0
g 12  7      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.3      0.46      0.52      0.5     0.0
h 12  7      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.0      0.01      0.00     -0.1     0.0
g 12  8      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.3     -0.35     -0.39     -0.3     0.0
h 12  8      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.0      0.02      0.13      0.3     0.0
g 12  9      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.4     -0.36     -0.37     -0.4     0.0
h 12  9      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.3      0.28      0.27      0.2     0.0
g 12 10      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.1      0.08      0.21      0.2     0.0
h 12 10      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.9     -0.87     -0.86     -0.9     0.0
g 12 11      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.2     -0.49     -0.77     -0.9     0.0
h 12 11      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.4     -0.34     -0.23     -0.1     0.0
g 12 12      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.4     -0.08      0.04      0.0     0.0
h 12 12      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.8      0.88      0.87      0.7     0.0
g 13  0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.2     -0.16     -0.09      0.0     0.0
g 13  1      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.9     -0.88     -0.89     -0.9     0.0
h 13  1      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.9     -0.76     -0.87     -0.9     0.0
g 13  2      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.3      0.30      0.31      0.4     0.0
h 13  2      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.2      0.33      0.30      0.4     0.0
g 13  3      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.1      0.28      0.42      0.5     0.0
h 13  3      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      1.8      1.72      1.66      1.6     0.0
g 13  4      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.4     -0.43     -0.45     -0.5     0.0
h 13  4      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.4     -0.54     -0.59     -0.5     0.0
g 13  5      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      1.3      1.18      1.08      1.0     0.0
h 13  5      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -1.0     -1.07     -1.14     -1.2     0.0
g 13  6      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.4     -0.37     -0.31     -0.2     0.0
h 13  6      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.1     -0.04     -0.07     -0.1     0.0
g 13  7      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.7      0.75      0.78      0.8     0.0
h 13  7      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.7      0.63      0.54      0.4     0.0
g 13  8      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.4     -0.26     -0.18     -0.1     0.0
h 13  8      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.3      0.21      0.10     -0.1     0.0
g 13  9      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.3      0.35      0.38      0.3     0.0
h 13  9      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.6      0.53      0.49      0.4     0.0
g 13 10      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.1     -0.05      0.02      0.1     0.0
h 13 10      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.3      0.38      0.44      0.5     0.0
g 13 11      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.4      0.41      0.42      0.5     0.0
h 13 11      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.2     -0.22     -0.25     -0.3     0.0
g 13 12      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.0     -0.10     -0.26     -0.4     0.0
h 13 12      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.5     -0.57     -0.53     -0.4     0.0
g 13 13      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0.1     -0.18     -0.26     -0.3     0.0
h 13 13      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0      0     -0.9     -0.82     -0.79     -0.8     0.0
    '''

    def read_coefficients(self, name=coeff):
        """
        !!FIXME!!  This code is fragile and should be made more robust.
        """
        c = {}  ;  mat = np.zeros([15,15], dtype='float')
        lines = self.coeff.split('\n')
        years = lines[4].split()[3:]
        years[-1] = years[-1].replace('2010-15','2015.0')  # this will fail in 2015  (and did)
        years[-1] = years[-1].replace('2015-20','2020.0')  # this will fail in 2020
#        print(years)
        years = np.array(years).astype('float')
        for year in years.astype('int'):
            c[year] = {'g':mat.copy(), 'h':mat.copy()}

        for line in lines[5:]:
            parts = line.split()
            if len(parts) <= 1: continue
            gh = parts[0]
            n, m = int(parts[1]), int(parts[2])
            val = np.array(parts[3:], dtype='float')
            for indx, year in enumerate(years.astype('int')):
                c[year][gh][m,n] = val[indx]

        #
        for gh in ['g','h']: c[years[-1]][gh] += c[years[-2]][gh]

        return c
            #print year,gh,n,m, indx,val[indx]
'''
    def odeint_func(self, xyz, t, *args):
        b = self.spherical(xyz[0], xyz[1], xyz[2])  ;# r, theta, phi
        b = np.array( [ b['r'], b['theta'], b['phi'] ] )
        b = b / np.sqrt( np.sum( b**2 ) )
        b = b * (100.0, 0.1, 0.1)
        return b
'''

#    coefficients = self.read_coefficients(coeff)

# This is consistent with scipy.special.lpnm
# (spFunc.lpmn(n=3, m=3, z=0.2))[0][:,2]
# Out[499]: array([-0.44      , -0.58787754,  2.88      ,  0.        ])
#
#http://www.mathworks.com/help/matlab/ref/legendre.html#f89-1002472
#Example 1
#The statement legendre(2,0:0.1:0.2) returns the matrix
#
# 	x = 0	x = 0.1	x = 0.2
# m = 0  -0.5000    -0.4850	-0.4400
# m = 1   0	    -0.2985	-0.5879
# m = 2   3.0000     2.9700	 2.8800

# http://hanspeterschaub.info/Papers/UnderGradStudents/MagneticField.pdf

class BasicTest(unittest.TestCase):

    def test_initialization(self):
        obj = igrfModel(verbose=1)
        obj = igrfModel(year=2000)
        obj = igrfModel(2000)
        obj = igrfModel(1900)
        obj = igrfModel(2015)
        obj = igrfModel(2011)
        obj = igrfModel(2011.5)
        obj = igrfModel(1899)
        obj = igrfModel(2016)

    def test_spherical(self):
        result = igrfModel(2000).spherical(r=6371.2e3, theta=0.0, phi=0.0) # Bx=27464.9, By=-3504.2, Bz=-14827.8)
        np.abs(result['field']['r'] - -55954.7) <= 0.1
        np.abs(result['field']['theta'] - 1785.1) <= 0.1
        np.abs(result['field']['phi'] - -881.0) <= 0.1

    def test_coordinates(self):
        igrf = igrfModel(2000)
        test = igrf.convert_coordinates(**dict(r=6371.2e3, theta=0.0, phi=0.0))
        test = igrf.convert_coordinates(cartesian=True, **dict(r=6371.2e3, theta=0.0, phi=0.0))
        test = igrf.convert_coordinates(geographic=True, **dict(r=6371.2e3, theta=0.0, phi=0.0))
        test = igrf.convert_coordinates(cartesian=True, geographic=True, **dict(r=6371.2e3, theta=0.0, phi=0.0))


# http://wdc.kugi.kyoto-u.ac.jp/cgi-bin/point-cgi
#test = dict( year=2000, latitude=0.0, longitude=0.0, height=0.0, Bx=27464.9, By=-3504.2, Bz=-14827.8)
#test = dict( year=2000, latitude=51.0, longitude=123.0, height=9876.0, Bx=20743.7, By=-3988.6, Bz=53964.9)
    def test_geographic(self):
        result = igrfModel(2000).geographic(0.0, 0.0, 0.0) # Bx=27464.9, By=-3504.2, Bz=-14827.8)
        np.abs(result['field']['north'] - +27464.9) <= 0.1
        np.abs(result['field']['east'] - -3504.2) <= 0.1
        np.abs(result['field']['up'] - +14827.8) <= 0.1

    def test_cartesian(self):
        result = igrfModel(2000).cartesian(0.0, 0.0, 6371.2e3) # Bx=27464.9, By=-3504.2, Bz=-14827.8)
        np.abs(result['field']['x'] - +27464.9) <= 0.1
        np.abs(result['field']['y'] - -3504.2) <= 0.1
        np.abs(result['field']['z'] - +14827.8) <= 0.1

if __name__ == "__main__":
    unittest.main()
#    igrf = igrfModel(2000)
#    test = igrf.convert_coordinates(**dict(r=6371.2e3, theta=0.0, phi=0.0))

    """ fixme: add more unit tests
    """
#    model = igrfModel()
#    test = model.spherical(6371.2e3, 0.1, 0.2)
#    print test, model._spherical_test(6371.2e3, 0.1, 0.2)

#    igrf = igrf_model()
#    print igrf.spherical(1e6,1,1, degree=13, potential=True) # 109 us
#    print igrf._spherical0(1e6,1,1, degree=13)  # 3.38 ms
#    print igrf._spherical1(1e6,1,1, degree=13)  # 287 us
#    print igrf._spherical2(1e6,1,1, degree=13)  # 155 us
#    print igrf._spherical3(1e6,1,1, degree=13)  # 150 us


######### Premature optimization is the root of all evil - Knuth ########
#
# The reference algorithm looks pretty competitive (1/2 speed)
#
# %timeit igrf_model().spherical(1e6,1,1, degree=13, potential=True)
# 100 loops, best of 3: 4.38 ms per loop
#
# %timeit igrf_model()._spherical0(1e6,1,1, degree=13)
# 100 loops, best of 3: 7.7 ms per loop


# Until we factor out the start-up time, then basic optimzations give 31x speedup
#
# %timeit igrf._spherical0(1e6,1,1, degree=13)
# 100 loops, best of 3: 3.39 ms per loop
#
# %timeit igrf.spherical(1e6,1,1, degree=13, potential=True)
# 10000 loops, best of 3: 109 µs per loop

# Everything I can think of *except* the dot product, and still 1.5x slower
#
# %timeit igrf._spherical3(1e6,1,1, degree=13)
# 10000 loops, best of 3: 150 µs per loop

# To do- start unit tests
#
# http://wdc.kugi.kyoto-u.ac.jp/cgi-bin/point-cgi
#test = dict( year=2000, latitude=0.0, longitude=0.0, height=0.0, Bx=27464.9, By=-3504.2, Bz=-14827.8)
#test = dict( year=2000, latitude=51.0, longitude=123.0, height=9876.0, Bx=20743.7, By=-3988.6, Bz=53964.9)

'''
## and of course this is really only stable in cartesian coordinates ##
igrf = igrfModel(2000)

def trace_conjugate(location, dstep=1e3):
    pos0 = igrf.convert_coordinates(**location)
    vec0 = igrf.spherical(pos0)
    pos1a = pos0 + vec0 * dstep
    vec1a = igrf.spherical(pos1a)  # Euler's method
    pos1b = 0.5*dstep * (vec0 + vec1a)  # Heun's method
    err = pos1b - pos1a   # overly pessimistic
'''

from scipy.integrate import odeint

def trace(xyz,t):
    q = igrf.cartesian( x=xyz[0], y=xyz[1], z=xyz[2])
    b = q['field']   #;  print q
    b = np.array( [ b['x'], b['y'], b['z'] ] )
    return b / np.sqrt(np.sum(b**2)) * 0.1 * 6371.2e3

t = np.linspace(0.0, 1.0e2, 100)
y0 = (6.6*6371.2e3, 0.0, 0.0 )
y1, infodict = odeint( trace, y0, t, full_output=True, h0=0.1, hmin=1e-3, hmax=1e6)
plt.clf() ; plt.plot( y1[:,0]/6371.2e3, y1[:,1]/6371.2e3, 'go-' )
