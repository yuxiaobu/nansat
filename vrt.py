# Name:    nansat.py
# Purpose: Container of VRT and GeolocationDomain classes
# Authors:      Asuka Yamakawa, Anton Korosov, Knut-Frode Dagestad,
#               Morten W. Hansen, Alexander Myasoyedov,
#               Dmitry Petrenko, Evgeny Morozov
# Created:      29.06.2011
# Copyright:    (c) NERSC 2011 - 2013
# Licence:
# This file is part of NANSAT.
# NANSAT is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.
# http://www.gnu.org/licenses/gpl-3.0.html
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
import tempfile

from nansat_tools import *

class GeolocationArray():
    '''Container for GEOLOCATION ARRAY data

    Keeps references to bands with X and Y coordinates, offset and step
    of pixel and line. All information is stored in dictionary self.d

    Instance of GeolocationArray is used in VRT and ususaly created in
    a Mapper.
    '''
    def __init__(self, xVRT=None, yVRT=None,
                 xBand=1, yBand=1, srs='', lineOffset=0, lineStep=1,
                 pixelOffset=0, pixelStep=1, dataset=None):
        '''Create GeolocationArray object from input parameters

        Parameters
        -----------
        xVRT : VRT-object or str
            VRT with array of x-coordinates OR string with dataset source
        yVRT : VRT-object or str
            VRT with array of y-coordinates OR string with dataset source
        xBand : number of band in the xDataset
        xBand : number of band in the yDataset
        srs : str, WKT
        lineOffset : int, offset of first line
        lineStep : int, step of lines
        pixelOffset : int, offset of first pixel
        pixelStep : step of pixels
        dataset : GDAL dataset to take geolocation arrays from

        Modifies
        ---------
        All input parameters are copied to self

        '''
        # dictionary with all metadata
        self.d = {}
        # VRT objects
        self.xVRT = None
        self.yVRT = None

        # make object from GDAL dataset
        if dataset is not None:
            self.d = dataset.GetMetadata('GEOLOCATION')
            return

        # make empty object
        if xVRT is None or yVRT is None:
            return

        if isinstance(xVRT, str):
            # make object from strings
            self.d['X_DATASET'] = xVRT
            self.d['Y_DATASET'] = yVRT
        else:
            # make object from VRTs
            self.xVRT = xVRT
            self.d['X_DATASET'] = xVRT.fileName
            self.yVRT = yVRT
            self.d['Y_DATASET'] = yVRT.fileName

        # proj4 to WKT
        if srs == '':
            sr = osr.SpatialReference()
            sr.ImportFromProj4('+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs')
            srs = sr.ExportToWkt()
        self.d['SRS'] = srs
        self.d['X_BAND'] = str(xBand)
        self.d['Y_BAND'] = str(yBand)
        self.d['LINE_OFFSET'] = str(lineOffset)
        self.d['LINE_STEP'] = str(lineStep)
        self.d['PIXEL_OFFSET'] = str(pixelOffset)
        self.d['PIXEL_STEP'] = str(pixelStep)


class VRT():
    '''Wrapper around GDAL VRT-file

    The GDAL VRT-file is an XML-file. It contains all metadata, geo-reference
    information and information ABOUT each band including band metadata,
    reference to the bands in the source file.
    VRT-class perfroms all operation on VRT-files: create, copy, modify,
    read, write, add band, add GeoTransform, SetProjection, etc. It uses
    either GDAL methods for these operations (e.g. Create, AddBand,
    SetMetadata, AutoCreateWarpedVRT, etc.) or reads/writes the XML-file
    directly (e.g. remove_geotransform, get_warped_vrt, etc).

    The core of the VRT object is GDAL dataset <self.dataset> generated
    by the GDAL VRT-Driver. The respective VRT-file is located in /vismem
    and has random name.

    GDAL data model doesn't have place for geolocaion arrays therefore
    VRT-object has instance of GeolocationArray self.geolocationArray-
    an object to keep information about Geolocation Arrays:
    reference to file with source data, pixel and line step and offset, etc.

    Domain has an instance of VRT-class <self.vrt>. It keeps only geo-
    reference information.

    All Mappers inherit from VRT. When Nansat opens file it loops through
    list of mappers, selects the one appropriate for the input file,
    and creates an instance of Mapper. But each Mapper has only a
    constructor, other methods are from VRT.

    Nansat has two instances of Mapper-class (<=VRT-class): self.raw and
    self.vrt. One holds VRT-file in original projection (derived from the
    input file), another - in modified projection.

    '''
    ComplexSource = Template('''
            <$SourceType>
                <SourceFilename relativeToVRT="0">$Dataset</SourceFilename>
                <SourceBand>$SourceBand</SourceBand>
                <NODATA>$NODATA</NODATA>
                <ScaleOffset>$ScaleOffset</ScaleOffset>
                <ScaleRatio>$ScaleRatio</ScaleRatio>
                <LUT>$LUT</LUT>
                <SrcRect xOff="0" yOff="0" xSize="$srcXSize" ySize="$srcYSize"/>
                <DstRect xOff="0" yOff="0" xSize="$dstXSize" ySize="$dstYSize"/>
            </$SourceType> ''')

    RawRasterBandSource = Template('''
            <VRTDataset rasterXSize="$XSize" rasterYSize="$YSize">
              <VRTRasterBand dataType="$DataType"
                band="$BandNum" subClass="VRTRawRasterBand">
                <SourceFilename relativeToVRT="0">$SrcFileName</SourceFilename>
                <ImageOffset>0</ImageOffset>
                <PixelOffset>$PixelOffset</PixelOffset>
                <LineOffset>$LineOffset</LineOffset>
              </VRTRasterBand>
            </VRTDataset> ''')

    ReprojectTransformer = Template('''
        <ReprojectTransformer>
          <ReprojectionTransformer>
            <SourceSRS>$SourceSRS</SourceSRS>
            <TargetSRS>$TargetSRS</TargetSRS>
          </ReprojectionTransformer>
        </ReprojectTransformer> ''')

    def __init__(self, gdalDataset=None, vrtDataset=None,
                 array=None,
                 srcGeoTransform=(0, 1, 0, 0, 0, 1),
                 srcProjection='',
                 srcRasterXSize=None,
                 srcRasterYSize=None,
                 srcGCPs=[],
                 srcGCPProjection='',
                 srcMetadata='',
                 geolocationArray=None,
                 nomem=False,
                 lat=None, lon=None):
        ''' Create VRT dataset from GDAL dataset, or from given parameters

        If vrtDataset is given, creates full copy of VRT content
        Otherwise takes reprojection parameters (geotransform, projection, etc)
        either from given GDAL dataset or from seperate parameters.
        Create VRT dataset (self.dataset) based on these parameters
        Adds logger

        Parameters
        -----------
        gdalDataset : GDAL Dataset
            source dataset of geo-reference
        vrtDataset : GDAL VRT Dataset
            source dataset of all content (geo-reference and bands)
        array : Numpy array
            source matrix with data
        srcGeoTransform : GDALGeoTransform
            parameter of geo-reference
        srcProjection : GDALProjection
            parameter of geo-reference
        srcRasterXSize : int
            parameter of geo-reference
        srcRasterYSize : int
            parameter of geo-reference
        srcMetadata : GDAL Metadata
            all global metadata
        geolocationArray : GeolocationArray
            object with info on geolocation array
            and VRTs with x/y datasets
        nomem : boolean, saves the vrt to a tempfile if nomem is True
        lon : Numpy array
            grid with longitudes
        lat : Numpy array
            grid with latitudes

        Modifies
        ---------
        self.dataset : GDAL VRT dataset
        self.logger : logging logger
        self.vrtDriver : GDAL Driver

        '''
        # essential attributes
        self.logger = add_logger('Nansat')
        self.fileName = self._make_filename(nomem=nomem)
        self.vrtDriver = gdal.GetDriverByName('VRT')
        self.vrt = None

        # open and parse wkv.xml
        fileNameWKV = os.path.join(os.path.dirname(
                                   os.path.realpath(__file__)), 'wkv.xml')
        self.wkvNode0 = Node.create(fileNameWKV)

        # default empty geolocation array of source
        srcGeolocationArray = GeolocationArray()
        if vrtDataset is not None:
            # copy content of the provided VRT dataset using CreateCopy
            self.logger.debug('copy content of the provided VRT '
                              'dataset using CreateCopy')
            self.dataset = self.vrtDriver.CreateCopy(self.fileName,
                                                     vrtDataset)
            # get source geolocation array
            srcGeolocationArray = GeolocationArray(dataset=vrtDataset)
        else:
            if gdalDataset is not None:
                # get geo-metadata from given GDAL dataset
                srcGeoTransform = gdalDataset.GetGeoTransform()
                srcProjection = gdalDataset.GetProjection()
                srcGCPs = gdalDataset.GetGCPs()
                srcGCPProjection = gdalDataset.GetGCPProjection()

                srcRasterXSize = gdalDataset.RasterXSize
                srcRasterYSize = gdalDataset.RasterYSize

                if not srcMetadata:
                    srcMetadata = gdalDataset.GetMetadata()
                # get source geolocation array
                srcGeolocationArray = GeolocationArray(dataset=gdalDataset)
            elif lat is not None and lon is not None:
                # get geo-metadata from given lat/lon grids
                srcRasterYSize, srcRasterXSize = lon.shape
                srcGCPs = self._latlon2gcps(lat, lon)
                srcGCPProjection = latlongSRS.ExportToWkt()
                latVRT = VRT(array=lat)
                lonVRT = VRT(array=lon)
                # create source geolocation array
                srcGeolocationArray = GeolocationArray(xVRT=lonVRT,
                                                       yVRT=latVRT)

            # create VRT dataset (empty or with a band from array)
            if array is None:
                self.dataset = self.vrtDriver.Create(self.fileName,
                                                     srcRasterXSize,
                                                     srcRasterYSize,
                                                     bands=0)
            else:
                self.create_dataset_from_array(array)

            # set geo-metadata in the VRT dataset
            self.dataset.SetGCPs(srcGCPs, srcGCPProjection)
            self.dataset.SetProjection(srcProjection)
            self.dataset.SetGeoTransform(srcGeoTransform)

            # set metadata
            self.dataset.SetMetadata(srcMetadata)

        # add geolocation array from input or from source data
        if geolocationArray is None:
            self.add_geolocationArray(srcGeolocationArray)
        else:
            self.add_geolocationArray(geolocationArray)

        # add self.fileName to metadata
        self.dataset.SetMetadataItem('fileName', self.fileName)

        # write file contents
        self.dataset.FlushCache()

        self.logger.debug('VRT self.dataset: %s' % self.dataset)
        self.logger.debug('VRT description: %s'
                          % self.dataset.GetDescription())
        #self.logger.debug('VRT metadata: %s ' % self.dataset.GetMetadata())
        self.logger.debug('VRT RasterXSize %d' % self.dataset.RasterXSize)
        self.logger.debug('VRT RasterYSize %d' % self.dataset.RasterYSize)

    def __del__(self):
        ''' Destructor deletes VRT and RAW files'''
        try:
            gdal.Unlink(self.fileName)
            gdal.Unlink(self.fileName.replace('vrt', 'raw'))
        except:
            pass

    def _make_filename(self, extention='vrt', nomem=False):
        '''Create random VSI file name

        Parameters
        ----------
        extention : string
            extension of the file

        Returns
        -------
        random file name

        '''
        if nomem:
            fd, filename = tempfile.mkstemp(suffix='.vrt')
            os.close(fd)
        else:
            allChars = ascii_uppercase + digits
            randomChars = ''.join(choice(allChars) for x in range(10))
            filename = '/vsimem/%s.%s' % (randomChars, extention)
        return filename

    def _create_bands(self, metaDict):
        ''' Generic function called from the mappers to create bands
        in the VRT dataset from an input dictionary of metadata

        Parameters
        ----------
        metaDict : list of dict with params of input bands and generated bands.
            Each dict has:
                'src' : dictionary with parameters of the sources:
                'dst' : dictionary with parameters of the generated bands

        Modifies
        ---------
        Adds bands to the self.dataset based on info in metaDict

        See Also
        ---------
        VRT._create_band()

        '''
        for bandDict in metaDict:
            src = bandDict['src']
            dst = bandDict.get('dst', None)
            self._create_band(src, dst)
            self.logger.debug('Creating band - OK!')
        self.dataset.FlushCache()

    def _create_band(self, src, dst=None):
        ''' Add band to self.dataset:

        Get parameters of the source band(s) from input
        Generate source XML for the VRT, add options of creating
        Call GDALDataset.AddBand
        Set source and options
        Add metadata

        Parameters
        ----------
        src : dict with parameters of sources:
            SourceFilename
            SourceBand
            ScaleRatio
            ScaleOffset
            NODATA
            LUT
            SourceType
            DataType
            ImageOffset (RawVRT)
            PixelOffset (RawVRT)
            LineOffset (RawVRT)
            ByteOrder (RawVRT)
        dst : dict with parameters of the created band
            name
            dataType
            wkv
            suffix
            AnyOtherMetadata
            PixelFunctionType: - band will be a pixel function defined by the
                                 corresponding name/value.
                                 In this case src may be list of
                                 dicts with parameters for each source.
                               - in case the dst band has a different datatype
                                 than the source band it is important to add a
                                 SourceTransferType parameter in dst
            SourceTransferType

        Returns
        --------
        name : string, name of the added band

        Examples
        --------
        vrt._create_band({'SourceFilename': filename, 'SourceBand': 1})
        vrt._create_band({'SourceFilename': filename, 'SourceBand': 2,
                          'ScaleRatio': 0.0001},
                         {'name': 'LAT', 'wkv': 'latitude'})
        vrt._create_band({'SourceFilename': filename, 'SourceBand': 2},
                         {'suffix': '670',
                          'wkv': 'brightness_temperature'})
        vrt._create_band([{'SourceFilename': filename, 'SourceBand': 1},
                          {'SourceFilename': filename, 'SourceBand': 1}],
                         {'PixelFunctionType': 'NameOfPixelFunction'})

        '''
        self.logger.debug('INPUTS: %s, %s " ' % (str(src), str(dst)))
        # Make sure src is list, ready for loop
        if type(src) == dict:
            srcs = [src]
        elif type(src) in [list, tuple]:
            srcs = src
        else:
            AttributeError('Wrong src!')

        # Check if dst is given, or create empty dict
        if dst is None:
            dst = {}

        # process all sources: check, set defaults, make XML
        srcDefaults = {'SourceBand': 1,
                       'LUT': '',
                       'NODATA': '',
                       'SourceType': 'ComplexSource',
                       'ScaleRatio': 1.0,
                       'ScaleOffset': 0.0}
        for src in srcs:
            # check if SourceFilename is given
            if 'SourceFilename' not in src:
                AttributeError('SourceFilename not given!')

            # set default values
            for srcDefault in srcDefaults:
                if srcDefault not in src:
                    src[srcDefault] = srcDefaults[srcDefault]

            # Find DataType of source (if not given in src)
            if src['SourceBand'] > 0 and 'DataType' not in src:
                self.logger.debug('SRC[SourceFilename]: %s'
                                  % src['SourceFilename'])
                srcDataset = gdal.Open(src['SourceFilename'])
                srcRasterBand = srcDataset.GetRasterBand(src['SourceBand'])
                src['DataType'] = srcRasterBand.DataType
                self.logger.debug('SRC[DataType]: %d' % src['DataType'])

            srcDs = gdal.Open(src['SourceFilename'])
            # create XML for each source
            src['XML'] = self.ComplexSource.substitute(
                Dataset=src['SourceFilename'],
                SourceBand=src['SourceBand'],
                SourceType=src['SourceType'],
                NODATA=src['NODATA'],
                ScaleOffset=src['ScaleOffset'],
                ScaleRatio=src['ScaleRatio'],
                LUT=src['LUT'],
                srcXSize=srcDs.RasterXSize,
                srcYSize=srcDs.RasterYSize,
                dstXSize=srcDs.RasterXSize,
                dstYSize=srcDs.RasterYSize)

        # create destination options
        if 'PixelFunctionType' in dst and len(dst['PixelFunctionType']) > 0:
            # in case of PixelFunction
            options = ['subClass=VRTDerivedRasterBand',
                       'PixelFunctionType=%s' % dst['PixelFunctionType']]
            if 'SourceTransferType' in dst:
                options.append('SourceTransferType=%s' %
                               dst['SourceTransferType'])
        elif len(srcs) == 1 and srcs[0]['SourceBand'] == 0:
            # in case of VRTRawRasterBand
            options = ['subclass=VRTRawRasterBand',
                       'SourceFilename=%s' % src['SourceFilename'],
                       'ImageOffset=%f' % src['ImageOffset'],
                       'PixelOffset=%f' % src['PixelOffset'],
                       'LineOffset=%f' % src['LineOffset'],
                       'ByteOrder=%s' % src['ByteOrder']]
        else:
            # in common case
            options = []
        self.logger.debug('Options of AddBand: %s', str(options))

        # set destination dataType (if not given in input parameters)
        if 'dataType' not in dst:
            if (len(srcs) > 1 or float(srcs[0]['ScaleRatio']) != 1.0 or
                    len(srcs[0]['LUT']) > 0 or 'DataType' not in srcs[0]):
                # if pixel function
                # if scaling is applied
                # if LUT
                # if source band not available: float32
                dst['dataType'] = gdal.GDT_Float32
            else:
                self.logger.debug('Set dst[dataType]: %d' % src['DataType'])
                #otherwise take the DataType from source
                dst['dataType'] = src['DataType']

        # Set destination name
        # get short_name from WKV.XML
        dstWKV = dst.get('wkv', '')
        wkvDict = self._get_wkv(dstWKV)
        self.logger.debug('wkvDict:%s' % str(wkvDict))
        wkvShortName = wkvDict.get('short_name', '')
        self.logger.debug('WKV short_name:%s' % wkvShortName)

        # merge wkv[short_name] and dst[suffix] if both given
        if ('name' not in dst and len(wkvShortName) > 0):
            dstSuffix = dst.get('suffix', '')
            if len(dstSuffix) > 0:
                dstSuffix = '_' + dstSuffix
            dst['name'] = wkvShortName + dstSuffix

        # create list of available bands (to prevent duplicate names)
        bandNames = []
        for iBand in range(self.dataset.RasterCount):
            bandNames.append(self.dataset.GetRasterBand(iBand + 1).
                             GetMetadataItem('name'))

        # if name is not given add 'band_00N'
        if 'name' not in dst:
            for n in range(999):
                bandName = 'band_%03d' % n
                if bandName not in bandNames:
                    dst['name'] = bandName
                    break
        # if name already exist add '_00N'
        elif dst['name'] in bandNames:
            for n in range(999):
                bandName = dst['name'] + '_%03d' % n
                if bandName not in bandNames:
                    dst['name'] = bandName
                    break

        self.logger.debug('dst[name]:%s' % dst['name'])

        # Add Band
        self.dataset.AddBand(int(dst['dataType']), options=options)
        dstRasterBand = self.dataset.GetRasterBand(self.dataset.RasterCount)

        # Append sources to destination dataset
        if len(srcs) == 1 and srcs[0]['SourceBand'] > 0:
            # only one source
            dstRasterBand.SetMetadataItem('source_0',
                                          str(src['XML']), 'new_vrt_sources')
        elif len(srcs) > 1:
            # several sources for PixelFunction
            metadataSRC = {}
            for i, src in enumerate(srcs):
                metadataSRC['source_%d' % i] = src['XML']

            dstRasterBand.SetMetadata(metadataSRC, 'vrt_sources')

        # set metadata from WKV
        dstRasterBand = self._put_metadata(dstRasterBand, wkvDict)

        # set metadata from provided parameters
        # remove and add params
        dst['SourceFilename'] = srcs[0]['SourceFilename']
        dst['SourceBand'] = str(srcs[0]['SourceBand'])
        dstRasterBand = self._put_metadata(dstRasterBand, dst)

        # return name of the created band
        return dst['name']

    def _set_time(self, time):
        ''' Set time of dataset and/or its bands

        Parameters
        ----------
        time : datetime

        If a single datetime is given, this is stored in
        all bands of the dataset as a metadata item 'time'.
        If a list of datetime objects is given, different
        time can be given to each band.

        '''
        # Make sure time is a list with one datetime element per band
        numBands = self.dataset.RasterCount
        if (isinstance(time, datetime.datetime) or
                isinstance(time, datetime.date)):
            time = [time]
        if len(time) == 1:
            time = time * numBands
        if len(time) != numBands:
            self.logger.error('Dataset has %s elements, '
                              'but given time has %s elements.'
                              % (str(numBands), str(len(time))))

        # Store time as metadata key 'time' in each band
        for i in range(numBands):
            iBand = self.dataset.GetRasterBand(i + 1)
            iBand.SetMetadataItem('time', str(time[i].isoformat()))

        return

    def _get_wkv(self, wkvName):
        ''' Get wkv from wkv.xml

        Parameters
        -----------
        wkvName : string
            value of 'wkv' key in metaDict

        Returns
        --------
        wkvDict : dictionay
            WKV corresponds to the given wkv_name

        '''
        wkvDict = {}
        for iNode in self.wkvNode0.nodeList('wkv'):
            tagsList = iNode.tagList()
            if iNode.node('standard_name').value == wkvName:
                wkvDict = {'standard_name': wkvName}
                for iTag in tagsList:
                    wkvDict[iTag] = str(iNode.node(iTag).value)
        return wkvDict

    def _put_metadata(self, rasterBand, metadataDict):
        ''' Put all metadata into a raster band

        Take metadata from metadataDict and put to the GDAL Raster Band

        Parameters
        ----------
        rasterBand : GDALRasterBand
            destination band without metadata

        metadataDict : dictionary
            keys are names of metadata, values are values

        Returns
        --------
        rasterBand : GDALRasterBand
            destination band with metadata

        '''
        self.logger.debug('Put: %s ' % str(metadataDict))
        for key in metadataDict:
            rasterBand.SetMetadataItem(key, str(metadataDict[key]))

        return rasterBand

    def create_dataset_from_array(self, array):
        '''Create a dataset with a band from an array

        Write contents of the array into flat binary file (VSI)
        Write VRT file with RawRastesrBand, which points to the binary file
        Open the VRT file as self.dataset with GDAL

        Parameters
        -----------
        array : numpy array

        Modifies
        ---------
        binary file is written (VSI)
        VRT file is written (VSI)
        self.dataset is opened

        '''
        arrayDType = array.dtype.name
        arrayShape = array.shape
        # create flat binary file from array (in VSI)
        binaryFile = self.fileName.replace('.vrt', '.raw')
        ofile = gdal.VSIFOpenL(binaryFile, 'wb')
        gdal.VSIFWriteL(array.tostring(), len(array.tostring()), 1, ofile)
        gdal.VSIFCloseL(ofile)
        array = None

        self.logger.debug('arrayDType: %s', arrayDType)

        #create conents of VRT-file pointing to the binary file
        dataType = {'uint8': 'Byte',
                    'int8': 'Byte',
                    'uint16': 'UInt16',
                    'int16': 'Int16',
                    'uint32': 'UInt32',
                    'int32': 'Int32',
                    'float32': 'Float32',
                    'float64': 'Float64',
                    'complex64': 'CFloat32',
                    'complex128': 'CFloat64'}.get(str(arrayDType))

        pixelOffset = {'Byte': '1',
                       'UInt16': '2',
                       'Int16': '2',
                       'UInt32': '4',
                       'Int32': '4',
                       'Float32': '4',
                       'Float64': '8',
                       'CFloat32': '8',
                       'CFloat64': '16'}.get(dataType)

        self.logger.debug('DataType: %s', dataType)

        lineOffset = str(int(pixelOffset) * arrayShape[1])
        contents = self.RawRasterBandSource.substitute(
            XSize=arrayShape[1],
            YSize=arrayShape[0],
            DataType=dataType,
            BandNum=1,
            SrcFileName=binaryFile,
            PixelOffset=pixelOffset,
            LineOffset=lineOffset)
        #write XML contents to
        self.write_xml(contents)

    def read_xml(self, inFileName=None):
        '''Read XML content of the VRT-file

        Parameters
        -----------
        inFileName : string, optional
            Name of the file to read XML from. self.fileName by default

        Returns
        --------
        string : XMl Content which is read from the VSI file

        '''
        # if no input file given, flush dataset content into VRT-file
        if inFileName is None:
            inFileName = str(self.fileName)
            self.dataset.FlushCache()

        #read from the vsi-file
        # open
        vsiFile = gdal.VSIFOpenL(inFileName, 'r')
        # get file size
        gdal.VSIFSeekL(vsiFile, 0, 2)
        vsiFileSize = gdal.VSIFTellL(vsiFile)
        # fseek to start again
        gdal.VSIFSeekL(vsiFile, 0, 0)
        # read
        vsiFileContent = gdal.VSIFReadL(vsiFileSize, 1, vsiFile)
        gdal.VSIFCloseL(vsiFile)
        return vsiFileContent

    def write_xml(self, vsiFileContent=None):
        '''Write XML content into a VRT dataset

        Parameters
        -----------
        vsiFileContent: string, optional
            XML Content of the VSI file to write

        Modifies
        ---------
        self.dataset
            If XML content was written, self.dataset is re-opened

        '''
        #write to the vsi-file

        vsiFile = gdal.VSIFOpenL(self.fileName, 'w')
        gdal.VSIFWriteL(vsiFileContent,
                        len(vsiFileContent), 1, vsiFile)
        gdal.VSIFCloseL(vsiFile)
        # re-open self.dataset with new content
        self.dataset = gdal.Open(self.fileName)

    def export(self, fileName):
        '''Export VRT file as XML into given <fileName>'''
        self.vrtDriver.CreateCopy(fileName, self.dataset)

    def copy(self):
        '''Creates full copy of VRT dataset'''
        try:
            # deep copy (everything including bands)
            vrt = VRT(vrtDataset=self.dataset,
                      geolocationArray=self.geolocationArray)
        except:
            # shallow copy (only geometadata)
            vrt = VRT(gdalDataset=self.dataset,
                      geolocationArray=self.geolocationArray)

        if 'adsVRTs' in dir(self):
            vrt.adsVRTs = self.adsVRTs

        # iterative copy of self.vrt
        print 'copy vrt.vrt'
        if self.vrt is not None:
            vrt.vrt = self.vrt.copy()
            if 'adsVRTs' in dir(self.vrt):
                vrt.vrt.adsVRTs = self.vrt.adsVRTs
            vrtXML = vrt.read_xml()
            node0 = Node.create(vrtXML)
            node0.node('SourceDataset').value = str(vrt.vrt.fileName)
            vrt.write_xml(str(node0.rawxml()))

        return vrt

    def add_geolocationArray(self, geolocationArray=None):
        ''' Add GEOLOCATION ARRAY to the VRT

        Parameters
        -----------
        geolocationArray: GeolocationArray object

        Modifes
        --------
        Add geolocationArray to self
        Sets GEOLOCATION ARRAY metadata

        '''
        if geolocationArray is None:
            geolocationArray = GeolocationArray()
        self.geolocationArray = geolocationArray

        # add GEOLOCATION ARRAY metadata  if geolocationArray is not empty
        if len(geolocationArray.d) > 0:
            self.dataset.SetMetadata(geolocationArray.d, 'GEOLOCATION')

    def remove_geolocationArray(self):
        ''' Remove GEOLOCATION ARRAY from the VRT

        Modifes
        --------
        Set self.geolocationArray to None
        Sets GEOLOCATION ARRAY metadata to ''

        '''
        self.geolocationArray.d = {}

        # add GEOLOCATION ARRAY metadata (empty if geolocationArray is empty)
        self.dataset.SetMetadata('', 'GEOLOCATION')

    def get_resized_vrt(self, xSize, ySize,
                        use_geolocationArray=False,
                        use_gcps=False, use_geotransform=False,
                        eResampleAlg=1, **kwargs):

        ''' Resize VRT

        Create Warped VRT with modidied RasterXSize, RasterYSize, GeoTransform

        Parameters
        -----------
        xSize, ySize : int
            new size of the VRT object
        eResampleAlg : GDALResampleAlg
            see also gdal.AutoCreateWarpedVRT

        Returns
        --------
        VRT object : Resized VRT object

        '''
        # get resize factor
        resizeFactor = float(xSize) / float(self.dataset.RasterXSize)
        geoTransform = list(self.dataset.GetGeoTransform())

        dstGCPs = []
        # get SRS
        dstSRS = self.dataset.GetProjection()
        if dstSRS == '':
            dstSRS = self.dataset.GetGCPProjection()
            geoTransform = None
            # Create resized GCPs
            srcGCPs = self.dataset.GetGCPs()
            for srcGCP in srcGCPs:
                dstGCP = gdal.GCP(srcGCP.GCPX,
                                  srcGCP.GCPY,
                                  srcGCP.GCPZ,
                                  srcGCP.GCPPixel * resizeFactor,
                                  srcGCP.GCPLine * resizeFactor,
                                  srcGCP.Info,
                                  srcGCP.Id)
                dstGCPs.append(dstGCP)

        # modify GeoTransform: set resolution from new X/Y size
        resizedGeoTransform = (0,
                               1.0 / resizeFactor,
                               0,
                               self.dataset.RasterYSize,
                               0,
                               -1.0 / resizeFactor)

        # update size and GeoTranform in XML of the warped VRT object
        reseizedVRT = self.get_warped_vrt(xSize=xSize, ySize=ySize,
                                   dstSRS=dstSRS,
                                   geoTransform=resizedGeoTransform,
                                   dstGCPs=dstGCPs,
                                   use_geolocationArray=use_geolocationArray,
                                   use_gcps=use_gcps,
                                   use_geotransform=use_geotransform,
                                   eResampleAlg=eResampleAlg)

        # if srcDs has geoTransform, set resized geoTransform
        if geoTransform is not None:
            geoTransform[1] = geoTransform[1] / resizeFactor
            geoTransform[5] = geoTransform[5] / resizeFactor
            geoTransform = tuple(geoTransform)
            reseizedVRT.dataset.SetGeoTransform(geoTransform)

        # set metadata
        vrtMetadata = reseizedVRT.vrt.dataset.GetMetadata()
        reseizedVRT.dataset.SetMetadata(vrtMetadata)

        return reseizedVRT


    def _remove_geotransform(self):
        '''Remove GeoTransfomr from VRT Object

        Modifies
        ---------
        The tag <GeoTransform> is revoved from the VRT-file

        '''
        # read XML content from VRT
        tmpVRTXML = self.read_xml()
        # find and remove GeoTransform
        node0 = Node.create(tmpVRTXML)
        node1 = node0.delNode('GeoTransform')
        # Write the modified elemements back into temporary VRT
        self.write_xml(str(node0.rawxml()))

    def _add_gcp_metadata(self, bottomup=True):
        '''Add GCPs to metadata (required e.g. by Nansat.export())

        Creates string representation of GCPs line/pixel/X/Y
        Adds these string to metadata

        Modifies
        ---------
        Add self.vrd.dataset.Metadata

        '''
        gcpNames = ['GCPPixel', 'GCPLine', 'GCPX', 'GCPY']
        gcps = self.dataset.GetGCPs()
        srs = self.dataset.GetGCPProjection()
        chunkLength = 5000

        # exit if no GCPs
        if len(gcps) == 0:
            return

        # add GCP Projection
        self.dataset.SetMetadataItem('NANSAT_GCPProjection',
                                     srs.replace(',',  '|').replace('"', '&'))

        # make empty strings
        gspStrings = ['', '', '', '']

        column = 0
        for gcp in gcps:
            if gcps[0].GCPLine == gcp.GCPLine:
                column += 1
            else:
                break

        # change the shape of gcps. (from 1D to 2D)
        row = len(gcps) / column
        gcps = list(gcps)
        gcps = zip(*[iter(gcps)]*column)

        # fill string with values
        for iRow in range(row):
            for jColumn in range(column):
                gspStrings[0] = '%s%05d| ' % (gspStrings[0],
                                              int(gcps[iRow][jColumn].GCPPixel))
                gspStrings[1] = '%s%05d| ' % (gspStrings[1],
                                              int(gcps[iRow][jColumn].GCPLine))
                # if bottomup is True (=image is filpped), gcps are flipped
                if bottomup:
                    gspStrings[2] = '%s%012.8f| ' % (gspStrings[2], gcps[row-iRow-1][jColumn].GCPX)
                    gspStrings[3] = '%s%012.8f| ' % (gspStrings[3], gcps[row-iRow-1][jColumn].GCPY)
                else:
                    gspStrings[2] = '%s%012.8f| ' % (gspStrings[2], gcps[iRow][jColumn].GCPX)
                    gspStrings[3] = '%s%012.8f| ' % (gspStrings[3], gcps[iRow][jColumn].GCPY)

        for i, gspString in enumerate(gspStrings):
            #split string into chunks
            numberOfChunks = int(float(len(gspString)) / chunkLength)
            chunki = 0
            for chunki in range(0, numberOfChunks + 1):
                chunk = gspString[(chunki * chunkLength):
                                  min(((chunki + 1) * chunkLength),
                                      len(gspString))]
                # add chunk to metadata
                self.dataset.SetMetadataItem('NANSAT_%s_%03d'
                                             % (gcpNames[i], chunki),
                                             chunk)

    def get_warped_vrt(self, dstSRS=None, eResampleAlg=0,
                       xSize=0, ySize=0, blockSize=None,
                       geoTransform=None, WorkingDataType=None,
                       tps=False, use_geolocationArray=True,
                       use_gcps=True, use_geotransform=True,
                       dstGCPs=[], dstGeolocationArray=None):

        ''' Create VRT object with WarpedVRT

        Modifies the input VRT according to the input options
        Creates simple WarpedVRT with AutoCreateWarpedVRT
        Modifies the WarpedVRT according to the input options

        The function tries to use geolocation array by default;
        if not present (or canceled) tries to use GCPs;
        if not present (or canceled) tries to use GeoTransform
        (either from input dataset or calculates a new one with dx=1,dy=-1).
        Three switches (use_geolocationArray, use_gcps, use_geotransform)
        allow to select which method to apply for warping. E.g.:
        # #1: srcVRT has GeolocationArray, geolocation array is used
        warpedVRT = srcVRT.get_warped_vrt(dstSRS, xSize, ySize,
                                             geoTransform)
        # #2: srcVRT has GeolocationArray, geolocation array is not used,
        # either GCPs (if present) or GeoTransform is used
        warpedVRT = srcVRT.get_warped_vrt(dstSRS, xSize, ySize,
                                             geoTransform,
                                             use_geolocationArray=False)
        # #3: srcVRT has GeolocationArray or GCPs, geolocation array is
        # not used, and GCPs are not used either.
        # Only input GeoTranform is used
        warpedVRT = srcVRT.get_warped_vrt(dstSRS, xSize, ySize,
                                             geoTransform,
                                             use_geolocationArray=False,
                                             use_gcps=False)

        # #4: srcVRT has whatever georeference, geolocation array is not used,
        # GCPs are not used, GeoTransform is not used either.
        # Artificial GeoTranform is calculated: (0, 1, 0, srcVRT.xSize, -1)
        # Warping becomes pure affine resize
        warpedVRT = srcVRT.get_warped_vrt(dstSRS, xSize, ySize,
                                             geoTransform,
                                             use_geolocationArray=False,
                                             use_gcps=False.,
                                             use_geotransform=false)

        If destination image has GCPs (provided in <dstGCPs>): fake GCPs for
        referencing line/piex of SRC image and X/Y of DST image are created
        and added to the SRC image. After warping dstGCPs are added to
        the WarpedVRT

        If destination image has geolocation array (provided in
        <dstGeolocationArray>):this geolocation array is added to the WarpedVRT


        Parameters
        -----------
        dstSRS : string
            WKT of the destination projection
        eResampleAlg : int (GDALResampleAlg)
            0 : NearestNeighbour,
            1 : Bilinear,
            2 : Cubic,
            3 : CubicSpline,
            4 : Lancoz
        xSize, ySize : int
            width and height of the destination rasetr
        geoTransform : tuple with 6 floats
            destination GDALGeoTransfrom
        dstGCPs : list with GDAL GCPs
            GCPs of the destination image
        dstGeolocationArray : GeolocationArray object
            Geolocation array of the destination object
        use_geolocationArray : Boolean (True)
            Use geolocation array in input dataset (if present) for warping
        use_gcps : Boolean (True)
            Use GCPs in input dataset (if present) for warping
        use_geotransform : Boolean (True)
            Use GeoTransform in input dataset for warping or make artificial
            GeoTransform : (0, 1, 0, srcVRT.xSize, -1)

        Returns
        --------
        warpedVRT : VRT object with WarpedVRT

        '''
        # VRT to be warped
        srcVRT = self.copy()

        # srs to be used in AutoCreateWarpedVRT
        acwvSRS = dstSRS

        # if destination GCPs are given: create and add fake GCPs to src
        if len(dstGCPs) > 0 and use_gcps:
            fakeGCPs = srcVRT._create_fake_gcps(dstGCPs)
            srcVRT.dataset.SetGCPs(fakeGCPs['gcps'], fakeGCPs['srs'])
            # don't use geolocation array
            use_geolocationArray = False
            acwvSRS = None

        # prepare VRT.dataset for warping.
        # Select if GEOLOCATION Array,
        # or GCPs, or GeoTransform from the original
        # dataset are used
        if len(self.geolocationArray.d) > 0 and use_geolocationArray:
            # use GEOLOCATION ARRAY by default
            # (remove GCP and GeoTransform)
            srcVRT.dataset.SetGCPs([], '')
            srcVRT._remove_geotransform()
        elif len(srcVRT.dataset.GetGCPs()) > 0 and use_gcps:
            # fallback to GCPs
            # (remove GeolocationArray and GeoTransform)
            srcVRT.dataset.SetMetadata('', 'GEOLOCATION')
            srcVRT._remove_geotransform()
        elif use_geotransform:
            # fallback to GeoTransform in input VRT
            # (remove GeolocationArray and GCP)
            srcVRT.dataset.SetMetadata('', 'GEOLOCATION')
            srcVRT.dataset.SetGCPs([], '')
        else:
            # fallback to simplest GeoTransform
            # (remove GeolocationArray and GCP and replace GeoTransform)
            srcVRT.dataset.SetMetadata('', 'GEOLOCATION')
            srcVRT.dataset.SetGCPs([], '')
            srcVRT.dataset.SetGeoTransform((0, 1, 0,
                                            srcVRT.dataset.RasterYSize, 0, -1))
        # create Warped VRT GDAL Dataset
        self.logger.debug('Run AutoCreateWarpedVRT...')
        warpedVRT = gdal.AutoCreateWarpedVRT(srcVRT.dataset, None,
                                             acwvSRS, eResampleAlg)

        # TODO: implement the below option for proper handling of
        # stereo projections
        # warpedVRT = gdal.AutoCreateWarpedVRT(srcVRT.dataset, '',
        #                                      dstSRS, eResampleAlg)

        # check if Warped VRT was created
        if warpedVRT is None:
            raise AttributeError('Cannot create warpedVRT!')

        # create VRT object from Warped VRT GDAL Dataset
        self.logger.debug('create VRT object from Warped VRT GDAL Dataset')
        warpedVRT = VRT(vrtDataset=warpedVRT)

        # set x/y size, geoTransform, blockSize
        self.logger.debug('set x/y size, geoTransform, blockSize')

        # Modify rasterXsize, rasterYsize and geotranforms in the warped VRT
        warpedXML = warpedVRT.read_xml()
        node0 = Node.create(warpedXML)

        if xSize > 0:
            node0.replaceAttribute('rasterXSize', str(xSize))
        if ySize > 0:
            node0.replaceAttribute('rasterYSize', str(ySize))

        if geoTransform is not None:
            invGeotransform = gdal.InvGeoTransform(geoTransform)
            # convert proper string style and set to the GeoTransform element
            node0.node('GeoTransform').value = str(geoTransform).strip('()')
            node0.node('DstGeoTransform').value = str(geoTransform).strip('()')
            node0.node('DstInvGeoTransform').value = (
                str(invGeotransform[1]).strip('()'))

            if node0.node('SrcGeoLocTransformer'):
                node0.node('BlockXSize').value = str(xSize)
                node0.node('BlockYSize').value = str(ySize)

            if blockSize is not None:
                node0.node('BlockXSize').value = str(blockSize)
                node0.node('BlockYSize').value = str(blockSize)

            if WorkingDataType is not None:
                node0.node('WorkingDataType').value = WorkingDataType

        """
        # TODO: test thoroughly and implement later
        if srcSRS is not None and dstSRS is not None:
            rt = self.ReprojectTransformer.substitute(SourceSRS=None,
                                                      TargetSRS=None)
            print 'rt', rt
            rtNode = Node.create(rt)
            print 'rtNode.xml()', rtNode.xml()
            giptNode = node0.node('GenImgProjTransformer')
            print 'giptNode', giptNode
            giptNode += rtNode
            print 'node0.xml()', node0.xml()
        """
        # overwrite XML of the warped VRT file with uprated size and geotranform
        warpedVRT.write_xml(str(node0.rawxml()))
        warpedVRT.export("c:/Users/asumak/Data/output/warpedVRT1217.vrt")
        # apply thin-spline-transformation option
        if use_gcps and tps:
            tmpVRTXML = warpedVRT.read_xml()
            tmpVRTXML = tmpVRTXML.replace('GCPTransformer', 'TPSTransformer')
            warpedVRT.write_xml(tmpVRTXML)
        """
        # TODO: implement the below option for proper handling stereo
        # projections over the pole get source projection from GCPs or
        # from dataset (TODO: or from GeolocationArray)
        if len(srcVRT.dataset.GetGCPs()) == 0:
            srcSRS = srcVRT.dataset.GetProjection()
        else:
            srcSRS = srcVRT.dataset.GetGCPProjection()
        # modify the VRT XML file
        """

        # if given, add dst GCPs
        self.logger.debug('if given, add dst GCPs')
        if len(dstGCPs) > 0:
            warpedVRT.dataset.SetGCPs(dstGCPs, dstSRS)
            warpedVRT._remove_geotransform()
            warpedVRT.dataset.SetProjection('')

        # if given, add dst GeolocationArray
        self.logger.debug('# if given, add dst GeolocationArray')
        if dstGeolocationArray is not None:
            warpedVRT._remove_geotransform()
            warpedVRT.add_geolocationArray(dstGeolocationArray)
            warpedVRT.dataset.SetProjection('')

        # Copy self into self.vrt
        warpedVRT.vrt = self.copy()

        # replace the reference from srcVRT to self
        self.logger.debug('replace the reference from srcVRT to self')
        rawFileName = str(os.path.basename(warpedVRT.vrt.fileName))
        warpedXML = str(warpedVRT.read_xml())
        node0 = Node.create(warpedXML)
        node1 = node0.node('GDALWarpOptions')
        node1.node('SourceDataset').value = '/vsimem/' + rawFileName
        warpedVRT.write_xml(str(node0.rawxml()))

        return warpedVRT

    def _create_fake_gcps(self, gcps):
        '''Create GCPs with reference self.pixel/line ==> dst.pixel/line

        GCPs from a destination image (dstGCP) are converted to a gcp of source
        image (srcGCP) this way:

        srcGCPPixel = srcPixel
        srcGCPLine = srcLine
        srcGCPX = dstGCPPixel = f(srcSRS, dstGCPX, dstGCPY)
        srcGCPY = dstGCPLine = f(srcSRS, dstGCPX, dstGCPY)

        Parameters
        -----------
        gcps : list
            GDAL GCPs

        Returns
        --------
        gcps : dict
            {'gcps': list with GDAL GCPs, 'srs': fake stereo WKT}

        '''
        # get source SRS (either Projection or GCPProjection)
        srcWKT = self.dataset.GetProjection()
        if srcWKT == '':
            srcWKT = self.dataset.GetGCPProjection()

        # the transformer converts lat/lon to pixel/line of SRC image
        srcTransformer = gdal.Transformer(self.dataset, None,
                                          ['SRC_SRS=' + srcWKT,
                                           'DST_SRS=' +
                                           latlongSRS.ExportToWkt()])

        # create 'fake' GCPs
        fakeGCPs = []
        for g in gcps:
            # transform DST lat/lon to SRC pixel/line
            succ, point = srcTransformer.TransformPoint(1, g.GCPX, g.GCPY)
            srcPixel = point[0]
            srcLine = point[1]

            # swap coordinates in GCPs:
            # pix1/line1 -> lat/lon  =>=>  pix2/line2 -> pix1/line1
            fakeGCPs.append(gdal.GCP(g.GCPPixel, g.GCPLine,
                                     0, srcPixel, srcLine))

        # create 'fake' STEREO projection for 'fake' GCPs of SRC image
        srsString = ('+proj=stere +lon_0=0 +lat_0=0 +k=1 '
                     '+ellps=WGS84 +datum=WGS84 +no_defs ')
        stereoSRS = osr.SpatialReference()
        stereoSRS.ImportFromProj4(srsString)
        stereoSRSWKT = stereoSRS.ExportToWkt()

        return {'gcps': fakeGCPs, 'srs': stereoSRSWKT}

    def _latlon2gcps(self, lat, lon, numOfGCPs=100):
        ''' Create list of GCPs from given grids of latitude and longitude

        take <numOfGCPs> regular pixels from inpt <lat> and <lon> grids
        Create GCPs from these pixels
        Create latlong GCPs projection

        Parameters
        -----------
        lat : Numpy grid
            array of latitudes
        lon : Numpy grid
            array of longitudes (should be the same size as lat)
        numOfGCPs : int, optional, default = 100
            number of GCPs to create

        Returns
        --------
        gcsp : List with GDAL GCPs

        '''
        # estimate step of GCPs
        gcpSize = np.sqrt(numOfGCPs)
        step0 = max(1, int(float(lat.shape[0]) / gcpSize))
        step1 = max(1, int(float(lat.shape[1]) / gcpSize))
        self.logger.debug('gcpCount: %d %d %f %d %d',
                          lat.shape[0], lat.shape[1], gcpSize, step0, step1)

        # generate list of GCPs
        gcps = []
        k = 0
        for i0 in range(0, lat.shape[0], step0):
            for i1 in range(0, lat.shape[1], step1):
                # create GCP with X,Y,pixel,line from lat/lon matrices
                gcp = gdal.GCP(float(lon[i0, i1]),
                               float(lat[i0, i1]),
                               0, i1, i0)
                self.logger.debug('%d %d %d %f %f',
                                  k, gcp.GCPPixel, gcp.GCPLine,
                                  gcp.GCPX, gcp.GCPY)
                gcps.append(gcp)
                k += 1

        return gcps

    def convert_GeolocationArray2GPCs(self, stepX=1, stepY=1):
        ''' Converting geolocation arrays to GCPs, and deleting the former

        When the geolocation arrays are much smaller than the raster bands,
        warping quality is very bad. This function is a temporary solution
        until (eventually) the problem with geolocation interpolation
        is solved:
        http://trac.osgeo.org/gdal/ticket/4907

        Parameters
        -----------
        stepX : int, optional (default 1)
        stepY : int, optional (default 1)
            If density of GCPs is too high, warping speed increases
            dramatically when using -tps (switch to gdalwarp).
            stepX and stepY can be adjusted to reduce density of GCPs
            (always keeping the ones around boundaries)

        Modifies
        ---------
        self.GCPs are added
        self.geolocationArray is removed

        '''
        geolocArray = self.dataset.GetMetadata('GEOLOCATION')
        x = self.geolocationArray.xVRT.dataset.GetRasterBand(2).ReadAsArray()
        y = self.geolocationArray.xVRT.dataset.GetRasterBand(1).ReadAsArray()
        numy, numx = x.shape
        PIXEL_OFFSET = int(geolocArray['PIXEL_OFFSET'])
        PIXEL_STEP = int(geolocArray['PIXEL_STEP'])
        LINE_OFFSET = int(geolocArray['LINE_OFFSET'])
        LINE_STEP = int(geolocArray['LINE_STEP'])
        pixels = np.linspace(PIXEL_OFFSET, PIXEL_OFFSET + (numx - 1) *
                             PIXEL_STEP, numx)
        lines = np.linspace(LINE_OFFSET, LINE_OFFSET + (numy - 1) *
                            LINE_STEP, numy)
        # Make GCPs
        GCPs = []
        # Subsample (if requested), but use linspace to
        # make sure endpoints are ntained
        for p in np.around(np.linspace(0, len(pixels) - 1, numx / stepX)):
            for l in np.around(np.linspace(0, len(lines) - 1, numy / stepY)):
                g = gdal.GCP(float(x[l, p]), float(y[l, p]), 0,
                             pixels[p], lines[l])
                GCPs.append(g)
        # Insert GCPs
        self.dataset.SetGCPs(GCPs, geolocArray['SRS'])
        # Delete geolocation array
        self.add_geolocationArray()

    def copyproj(self, fileName):
        ''' Copy geoloctation data from given VRT to a figure file

        Useful for adding geolocation information to figure
        files produced e.g. by Figure class, which contain no geolocation.
        Analogue to utility gdalcopyproj.py.

        Parameters
        -----------
        fileName : string
            Name of file to which the geolocation data shall be written

        '''
        figDataset = gdal.Open(fileName, gdal.GA_Update)
        figDataset.SetGeoTransform(self.dataset.GetGeoTransform())
        figDataset.SetProjection(self.dataset.GetProjection())
        gcps = self.dataset.GetGCPs()
        if len(gcps) != 0:
            figDataset.SetGCPs(gcps, self.dataset.GetGCPProjection())
        figDataset = None  # Close and write output file

    def delete_band(self, bandNum):
        ''' Delete a band from the given VRT

        Parameters
        ----------
        bandNum : int
            band number

        '''
        node0 = Node.create(self.read_xml())
        node0.delNode('VRTRasterBand', options={'band': bandNum})
        self.write_xml(str(node0.rawxml()))

    def delete_bands(self, bandNums):
        ''' Delete bands

        Parameters
        ----------
        bandNums : list
            elements are int

        '''
        bandNums.sort()
        bandNums.reverse()
        for iBand in bandNums:
            self.delete_band(iBand)

    def set_subsetMask(self, maskDs, xOff, yOff, dstXSize, dstYSize):
        ''' Add maskband and modify xml to proper size

        Parameters
        ----------
        maskDs : dataset
            gdal dataset (mask)
        xOff, yOff : int
            offset of the subset based on the underlying dataset
        dstXSize, dstYSize : int
            size of the subset data

        '''
        # create empty maskband
        self.dataset.CreateMaskBand(gdal.GMF_PER_DATASET)
        self.dataset = self.vrtDriver.CreateCopy(self.fileName, self.dataset)

        # get source bandsize
        srcXSize = self.dataset.RasterXSize
        srcYSize = self.dataset.RasterYSize

        # read xml and create the node
        XML = self.read_xml()
        node0 = Node.create(XML)

        # replace the rastersize to the masked raster size
        node0.replaceAttribute('rasterXSize', str(dstXSize))
        node0.replaceAttribute('rasterYSize', str(dstYSize))

        # replace source band data to masked band data
        for iNode in node0.nodeList('VRTRasterBand'):
            node1 = iNode.node('ComplexSource').node('SrcRect')
            node1.replaceAttribute('xOff', str(xOff))
            node1.replaceAttribute('yOff', str(yOff))
            node1.replaceAttribute('xSize', str(dstXSize))
            node1.replaceAttribute('ySize', str(dstYSize))
            node1 = iNode.node('ComplexSource').node('DstRect')
            node1.replaceAttribute('xSize', str(dstXSize))
            node1.replaceAttribute('ySize', str(dstYSize))

        # create contents for mask band
        contents = self.ComplexSource.substitute(
            SourceType='SimpleSource',
            Dataset=maskDs.GetDescription(),
            SourceBand='mask,1',
            NODATA='',
            ScaleOffset='',
            ScaleRatio='',
            LUT='',
            srcXSize=srcXSize,
            srcYSize=srcYSize,
            dstXSize=dstXSize,
            dstYSize=dstYSize)

        # add mask band contents to xml
        contents = node0.node('MaskBand').node('VRTRasterBand').insert(contents)
        node0.node('MaskBand').delNode('VRTRasterBand')
        contents = node0.insert(contents, 'MaskBand')

        # write contents
        self.write_xml(contents)

    def get_shifted_vrt(self, shiftDegree):
        ''' Roll data in bands westwards or eastwards

        Create shiftVRT which references self. Modify georeference
        of shiftVRT to account for the roll. Add as many bands as in self
        but for each band create two complex sources: for western
        and eastern parts. Keep self in shiftVRT.vrt

        Parameters
        ----------
        shiftDegree : float
            rolling angle, how far east/west to roll

        Returns
        -------
        shiftVRT : VRT object with rolled bands

        '''
        # Copy self into self.vrt
        shiftVRT = VRT(gdalDataset=self.dataset)
        shiftVRT.vrt = self.copy()

        if shiftDegree < 0:
            shiftDegree += 360.0

        geoTransform = shiftVRT.vrt.dataset.GetGeoTransform()
        shiftPixel = int(shiftDegree / float(geoTransform[1]))
        geoTransform = list(geoTransform)
        geoTransform[0] = round(geoTransform[0] + shiftDegree, 3)
        newEastBorder = geoTransform[0] + (geoTransform[1] *
                                           shiftVRT.dataset.RasterXSize)
        if newEastBorder > 360.0:
            geoTransform[0] -= 360.0
        shiftVRT.dataset.SetGeoTransform(tuple(geoTransform))

        # Add bands to self
        for iBand in range(shiftVRT.vrt.dataset.RasterCount):
            src = {'SourceFilename': shiftVRT.vrt.fileName,
                   'SourceBand': iBand + 1}
            dst = shiftVRT.vrt.dataset.GetRasterBand(iBand+1).GetMetadata()
            shiftVRT._create_band(src, dst)

        # read xml and create the node
        XML = shiftVRT.read_xml()
        node0 = Node.create(XML)

        # divide into two bands and switch the bands
        for i in range(len(node0.nodeList('VRTRasterBand'))):
            # create i-th 'VRTRasterBand' node
            node1 = node0.node('VRTRasterBand', i)
            # modify the 1st band
            shiftStr = str(shiftPixel)
            sizeStr = str(shiftVRT.vrt.dataset.RasterXSize - shiftPixel)
            node1.node('ComplexSource').node('DstRect').replaceAttribute('xOff', shiftStr)
            node1.node('ComplexSource').node('DstRect').replaceAttribute('xSize', sizeStr)
            node1.node('ComplexSource').node('SrcRect').replaceAttribute('xSize', sizeStr)

            # add the 2nd band
            xmlSource = node1.xml()
            dom = xdm.parseString(xmlSource)
            cloneNode = Node.create(dom).node('ComplexSource')
            cloneNode.node('SrcRect').replaceAttribute('xOff', sizeStr)
            cloneNode.node('DstRect').replaceAttribute('xOff', str(0))
            cloneNode.node('SrcRect').replaceAttribute('xSize', shiftStr)
            cloneNode.node('DstRect').replaceAttribute('xSize', shiftStr)

            contents = node0.insert(cloneNode.xml(), 'VRTRasterBand', i)
            # overwrite the modified contents and create a new node
            dom = xdm.parseString(contents)
            node0 = Node.create(dom)

        # write down XML contents
        shiftVRT.write_xml(str(node0.rawxml()))

        return shiftVRT
