import numpy as np
import sys, os
baseDir = os.path.dirname(os.path.abspath(__file__))
sys.path.append('{0}/build'.format(baseDir))
sys.path.insert(0, '/home/adif/MichaelBusta/caffe/Release/install/python')
import caffe
import cv2
import math, time
from models import create_models_tiny
import vis
from utils import get_normalized_image, print_seq_ext, print_seq2, get_obox, process_splits
import cmp_trie

from PIL import Image
from PIL import ImageFont
from PIL import ImageDraw 

from imutils.video import VideoStream
from imutils.video import FPS
import argparse

image_no = 0
buckets = [54, 80, 124, 182, 272, 410, 614, 922, 1383, 2212]      
image_size = [544, 544]
it = 0
mean_rec = 0
gt_all = 0
gt_loc = 0
wr_good_all = 0

debug = False

rec_t = 0.6
ext_factor = 1.1
ext_factorx = 1.3

ap = argparse.ArgumentParser()
ap.add_argument("-p", "--prototxt", required=True,
	help="path to Caffe 'deploy' prototxt file")
ap.add_argument("-m", "--model", required=True,
	help="path to Caffe pre-trained model")
ap.add_argument("-i", "--input", required=True,
	help="path to Caffe pre-trained model")
ap.add_argument("-c", "--confidence", type=float, default=0.2,
	help="minimum probability to filter weak detections")
args = vars(ap.parse_args())

net = cv2.dnn.readNetFromCaffe(args["prototxt"], args["model"])

CLASSES = ["background", "plate"]
print("[INFO] loading model...")
print("[INFO] starting video stream...")
# vs = cv2.VideoCapture('Plate Detection Testing.mp4')
vs = cv2.VideoCapture(args["input"])
# vs = cv2.VideoCapture(1)
time.sleep(2.0)
fpsDisplay = FPS().start()

def forwared_image(nets, scaled, original):
    global rec_t, ext_factor, ext_factorx
    net, net_ctc = nets

    img = [scaled]
    draw = img[0]

    imgo = original

    im = np.asarray(img, dtype=np.float)
    im = im / 128.0
    im = im - 1.0
    #im = im.reshape((3, im.shape[0], im.shape[1]))
    im = np.swapaxes(im,1,3)
    im = np.swapaxes(im,2,3)

    net.blobs['data'].reshape(im.shape[0],im.shape[1],im.shape[2],im.shape[3])
    net.blobs['data'].data[...] = im
    net.reshape()
    start = time.time()
    out = net.forward(start="conv1")
    end = time.time()
    seconds = end - start
    fps = 1 / seconds 
    #print("loc fps:{0}".format(fps))
    
    boxes  = out['boxes']
    
    boxes[0, 0, :, 0] *= image_size[0]
    boxes[0, 0, :, 1] *= image_size[1]
    normFactor = math.sqrt(image_size[1] * image_size[1] + image_size[0] * image_size[0])
    boxes[0, 0, :, 2] *= normFactor
    boxes[0, 0, :, 3] *= normFactor
    
    nms = boxes[0, 0, :, 8] != 1
    boxes = boxes[:, :, nms, :]
    
    boxes_count = 0
    for i in range(0, boxes.shape[2]):
        det_word = boxes[0, 0, i]
        if (det_word[0] == 0 and det_word[1] == 0) or det_word[5] < 0.1:
            break
        boxes_count += 1
    
    detections_out = []
    
    
    for i in range(0, boxes_count):  
        det_word = boxes[0, 0, i]
        boxr  = ((det_word[0], det_word[1]), (det_word[2], det_word[3]), det_word[4] * 180 / 3.14)
        box = cv2.boxPoints(boxr)
        
        box = np.array(box, dtype="int")
        #vis.draw_box_points(draw, box, (255, 0, 0))
        bbox = cv2.boundingRect(box)
        bbox = [bbox[0], bbox[1], bbox[2], bbox[3]]
        bbox[2] += bbox[0]
        bbox[3] += bbox[1]
                
        boxro  = [[det_word[0], det_word[1]], [det_word[2]  * ext_factorx, det_word[3] * ext_factor], det_word[4] * 180 / 3.14]
        boxt = get_obox(img[0], original, boxro)
        boxt = ((boxt[0][0], boxt[0][1]), (boxt[1][0], boxt[1][1]), boxt[2])
        
        norm2, rot_mat = get_normalized_image(original, boxt)
        if norm2 is None:
            continue
        
        norm = cv2.cvtColor(norm2, cv2.COLOR_BGR2GRAY )                 
        
        width_scale = 32.0 / norm2.shape[0]
        width = norm.shape[1] * width_scale
        best_diff = width
        bestb = 0
        for b in range(0, len(buckets)):
            if best_diff > abs(width - buckets[b]):
                best_diff = abs(width  - buckets[b])
                bestb = b
            
        scaled = cv2.resize(norm, (buckets[bestb], 32))  
        
        #cv2.imshow('norm2', scaled)
        
        imtf = np.asarray([scaled], dtype=np.float)
        imtf = np.asarray(imtf, dtype=np.float)
        delta = imtf.max() - imtf.min()
        imtf /= (delta / 2)
        imtf -= imtf.mean()
        imtf = np.reshape(imtf, (imtf.shape[0], -1, imtf.shape[1], imtf.shape[2])) 
            
        net_ctc.blobs['data'].reshape(imtf.shape[0],imtf.shape[1],imtf.shape[2], imtf.shape[3]) 
        net_ctc.blobs['data'].data[...] = imtf
        
        outctc = net_ctc.forward()
        ctc_f = outctc['softmax'] 
        
        ctc_f = ctc_f.reshape(ctc_f.shape[0], ctc_f.shape[1], ctc_f.shape[3])
        labels = ctc_f.argmax(2)
        mask = labels > 2
        masked = ctc_f.max(2)[mask]
        mean_conf = np.sum(masked) / masked.shape[0]
        
        if mean_conf < 0.2:
            vis.draw_box_points(scaled, box, color = (0, 0, 0))
            continue
        
        if debug:    
            vis.vis_square(imtf[0])
        
        
        
        det_text, conf, dec_s = print_seq_ext(labels[:, 0], np.sum(masked) ) 
        
        if len(det_text) == 0:
            continue
        
        if len(det_text) < 3 and mean_conf < 0.8:
            continue
        
        #detections_out.append( (boxt, (det_text, mean_conf, int(det_word[6])) ) )
        #continue
    
        splits_raw = process_splits(det_text, conf, dec_s, norm2, ctc_f, rot_mat, boxt, original, 0, mean_conf, alow_non_dict=True)
        detections_out.extend( splits_raw )
        #continue
        
        #if out_raw is not None:
        #    out_raw.write(u"{0}|{1}|{2}|{3}|{4}|{5}|{6}|{7}|{8}|{9}|{10}|{11}\n".format(\
        #                'vid',box[0, 0],box[0, 1], box[1, 0], box[1, 1], \
        #                box[2, 0], box[2, 1], box[3, 0], box[3, 1], det_text, det_text, mean_conf).encode('utf8'))
        
        
        dec2, conf2, dec_splits = cmp_trie.decode_sofmax(ctc_f.reshape(ctc_f.shape[0], ctc_f.shape[2]))
        best_dict = print_seq2(dec2[0])
        
        if len(best_dict) == 0:
            continue
        splits_out = process_splits(best_dict, conf2, dec_splits, norm2, ctc_f, rot_mat, boxt, original, 1, mean_conf)
        detections_out.extend( splits_out )
        
    return detections_out, fps

def test_pic(nets):
    global rec_t, image_size

    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 16)
    font2 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 18)

    while True:
        ret, im = vs.read()
        height = im.shape[0]
        width = im.shape[1]
        blob = cv2.dnn.blobFromImage(cv2.resize(im, (300, 300)),
            0.007843, (300, 300), 127.5)
        net.setInput(blob)
        detections = net.forward()

        for i in np.arange(0, detections.shape[2]):
            confidence = detections[0,0,i,2]
            if i != 0:
                continue
            else:
                if confidence > 0.2:
                    idx = int(detections[0, 0, i, 1])
                    box = detections[0, 0, i, 3:7] * np.array([width, height, width, height])
                    (startX, startY, endX, endY) = box.astype("int")
                    label = "{}: {:.2f}%".format(CLASSES[idx],
                        confidence * 100)
                    cv2.rectangle(im, (startX-10, startY), (endX, endY),
                        (0,255,0), 2)
                    y = startY - 15 if startY - 15 > 15 else startY + 15
                    cv2.putText(im, label, (startX, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 2)
                    topPlat = int((endY-startY)*0.72)
                    endY = topPlat + startY
                    ROI = im[startY:endY, startX-10:endX]
                    (hROI, wROI) = ROI.shape[:2]
                    midROI = int(0.6*wROI)
                    leftROI = int(0.3*wROI)
                    fpsDisplay.update()
            
            cv2.imshow("Frame", im)
            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                break
            elif key == ord("a"):
                # cv2.imshow("ROI", ROI)
                # print(hROI)
                # print(wROI)

                image_size = [200 / 64 * 64, 80 / 64 * 64]

                scaled = cv2.resize(ROI, (image_size[0], image_size[1]))
                if nets[0].blobs['data'].data[...].shape[1] == 1:
                    scaled = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY )
                    scaled = scaled.reshape((scaled.shape[0], scaled.shape[1], 1))

                detections_out, fps = forwared_image(nets, scaled, ROI)
                
                img = Image.fromarray(ROI)
                draw = ImageDraw.Draw(img)
                for detection in detections_out:  
                    text = detection[1][0]
                    
                    width, height = draw.textsize(text, font=font)
                    center =  [detection[0][0][0] - width / 2, detection[0][0][1] - 10]
                    
                    sx = int(detection[0][0][0] - width / 2)
                    ex = int(detection[0][0][0] + width / 2)
                    sy = int(detection[0][0][1] - 10)
                    ey = int(detection[0][0][1] + 10)
                    
                    ROI[sy:ey, sx:ex] = ROI[sy:ey, sx:ex] / 2 
                    
                    boxr  = ((detection[0][0][0], detection[0][0][1]), (detection[0][1][0], detection[0][1][1]), detection[0][2])
                    box = cv2.boxPoints(boxr)  
                    color = (0, 255, 0)
                    vis.draw_box_points(ROI, box, color, thickness = 1)
                
                img = Image.fromarray(ROI)
                draw = ImageDraw.Draw(img)  
                centerArr = []      
                result = []
                charOutput = ""
                for detection in detections_out:
                    text = detection[1][0]
                    width, height = draw.textsize(text, font=font)
                    center =  [detection[0][0][0] - width / 2, detection[0][0][1] - 10]
                    draw.text((center[0], center[1]), text, fill = (0,255,0),font=font)
                    if len(text) >= 1 and (len(result) < 3 and center[0] < leftROI):
                        result.insert(0, text)
                    elif (len(text) >=1  and len(result) < 3) and (center[0] >= leftROI and center[0] < midROI):
                        result.insert(1, text)  
                    elif (len(text) >= 1 and len(text) < 4) and (len(result) < 3 and center[0] > midROI):
                        result.insert(2, text)
                char = charOutput.join(result)
                print(char)
                
                pix = np.array(img)
                if pix.shape[0] > 1024:
                    pix = cv2.resize(pix, (pix.shape[1] / 2, pix.shape[0] / 2))

                cv2.imshow("Output", ROI)
                
                fpsDisplay.stop()
                # cv2.putText(im, "FPS: {:.2f}".format(fpsDisplay.elapsed()), (30, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 2)
                print("FPS: {:.2f}".format(fpsDisplay.fps()))

                # cv2.waitKey()

if __name__ == '__main__':
    caffe.set_mode_gpu() 
    nets = create_models_tiny(caffe.TEST)
    yolonet = nets[0]        
    net_ctc = nets[1]    
    test_pic(nets)