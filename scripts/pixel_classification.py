#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#
# Copyright (c) 2020-2024 University of Dundee.
#
#   Redistribution and use in source and binary forms, with or without modification, 
#   are permitted provided that the following conditions are met:
# 
#   Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
#   Redistributions in binary form must reproduce the above copyright notice, 
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#   THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
#   ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
#   OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
#   IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, 
#   INCIDENTAL, SPECIAL, EXEMPLARY OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
#   PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
#   HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
#   (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED
#   OF THE POSSIBILITY OF SUCH DAMAGE.
#
# Version: 1.0
#

import numpy
import os

import omero.clients
from omero.gateway import BlitzGateway
from getpass import getpass
from collections import OrderedDict

from ilastik import app
from ilastik.applets.dataSelection.opDataSelection import PreloadedArrayDatasetInfo  # noqa


# Connect to the server
def connect(hostname, username, password):
    conn = BlitzGateway(username, password,
                        host=hostname, secure=True)
    conn.connect()
    return conn


# Load-images
def load_images(conn, dataset_id):
    return conn.getObjects('Image', opts={'dataset': dataset_id})


# Create-dataset
def create_dataset(conn, dataset_id):
    dataset = omero.model.DatasetI()
    v = "ilastik_probabilities_from_dataset_%s" % dataset_id
    dataset.setName(omero.rtypes.rstring(v))
    v = "ilatisk results probabilities from Dataset:%s" % dataset_id
    dataset.setDescription(omero.rtypes.rstring(v))
    return conn.getUpdateService().saveAndReturnObject(dataset)


# Load-data
def load_numpy_array(image):
    pixels = image.getPrimaryPixels()
    size_z = image.getSizeZ()
    size_c = image.getSizeC()
    size_t = image.getSizeT()
    size_y = image.getSizeY()
    size_x = image.getSizeX()
    z, t, c = 0, 0, 0  # first plane of the image
    zct_list = []
    for t in range(size_t):
        for z in range(size_z):  # get the Z-stack
            for c in range(size_c):  # all channels
                zct_list.append((z, c, t))
    values = []
    # Load all the planes as YX numpy array
    planes = pixels.getPlanes(zct_list)
    j = 0
    k = 0
    tmp_c = []
    tmp_z = []
    s = "z:%s t:%s c:%s y:%s x:%s" % (size_z, size_t, size_c, size_y, size_x)
    print(s)
    # axis tzyxc
    print("Downloading image %s" % image.getName())
    for i, p in enumerate(planes):
        if k < size_z:
            if j < size_c:
                tmp_c.append(p)
                j = j + 1
                if j == size_c:
                    # use dstack to have c at the end
                    tmp_z.append(numpy.dstack(tmp_c))
                    tmp_c = []
                    j = 0
                    k = k + 1
        if k == size_z:  # done with the stack
            values.append(numpy.stack(tmp_z))
            tmp_z = []
            k = 0
    return numpy.stack(values)


# Analyze-data
def analyze(conn, images, model, new_dataset):
    # Prepare ilastik
    os.environ["LAZYFLOW_THREADS"] = "2"
    os.environ["LAZYFLOW_TOTAL_RAM_MB"] = "2000"
    args = app.parse_args([])
    args.headless = True
    args.project = model
    shell = app.main(args)
    for image in images:
        input_data = load_numpy_array(image)
        # run ilastik headless
        print('running ilastik using %s and %s' % (model, image.getName()))
        data = [ {"Raw Data": PreloadedArrayDatasetInfo(preloaded_array=input_data, axistags=vigra.defaultAxistags("tzyxc"))}]  # noqa
        predictions = shell.workflow.batchProcessingApplet.run_export(data,
                                                                      export_to_array=True)  # noqa
        for d in predictions:
            save_results(conn, image, d, new_dataset)


# Save-results
def save_results(conn, image, data, dataset):
    filename, file_extension = os.path.splitext(image.getName())
    # Save the probabilities file as an image
    print("Saving Probabilities as an Image in OMERO")
    name = filename + "_Probabilities"
    desc = "ilastik probabilities from Image:%s" % image.getId()
    # Re-organise array from tzyxc to zctyx order expected by OMERO
    data = data.swapaxes(0, 1).swapaxes(3, 4).swapaxes(2, 3).swapaxes(1, 2)

    def plane_gen():
        """
        Set up a generator of 2D numpy arrays.
        The createImage method below expects planes in the order specified here
        (for z.. for c.. for t..)
        """
        size_z = data.shape[0]-1
        for z in range(data.shape[0]):  # all Z sections data.shape[0]
            print('z: %s/%s' % (z, size_z))
            for c in range(data.shape[1]):  # all channels
                for t in range(data.shape[2]):  # all time-points
                    yield data[z][c][t]

    conn.createImageFromNumpySeq(plane_gen(), name, data.shape[0],
                                 data.shape[1], data.shape[2],
                                 description=desc, dataset=dataset)


# Disconnect
def disconnect(conn):
    conn.close()


# main
def main():
    try:
        # Collect user credentials
        host = input("Host [wss://workshop.openmicroscopy.org/omero-ws]: ") or 'wss://workshop.openmicroscopy.org/omero-ws'  # noqa
        username = input("Username [trainer-1]: ") or 'trainer-1'
        password = getpass("Password: ")
        dataset_id = input("Dataset ID [6210]: ") or '6210'
        # Connect to the server
        conn = connect(host, username, password)
        conn.c.enableKeepAlive(60)

        # path to the ilastik project
        ilastik_project = "../notebooks/pipelines/ilastik14-Nov-2024.ilp"

        # Load the images in the dataset
        images = load_images(conn, dataset_id)

        new_dataset = create_dataset(conn, dataset_id)

        analyze(conn, images, ilastik_project, new_dataset)

    finally:
        disconnect(conn)
    print("done")


if __name__ == "__main__":
    main()
