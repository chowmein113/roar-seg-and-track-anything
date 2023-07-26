import tools.roar_tools as rt
from RoarSegTracker import RoarSegTracker
import json
import os
import cv2
from model_args import aot_args,sam_args,segtracker_args
from PIL import Image
from aot_tracker import _palette
import numpy as np
import torch
import imageio
import matplotlib.pyplot as plt
from scipy.ndimage import binary_dilation
from datetime import datetime
import gc
import tqdm
class MainHub():
    """
    Main hub class for RoarSegTracker
    
    Class structure of main for use of RoarSegTracker
    """
    def __init__(self, segtracker_args={}, sam_args={}, aot_args={}, photo_dir="", 
                 annotation_dir="", output_dir=""):
        self.segtracker_args = segtracker_args
        self.sam_args = sam_args
        self.aot_args = aot_args
        self.photo_dir = photo_dir
        self.annotation_dir = annotation_dir
        self.output_dir = output_dir
        self.track_key_frame_mask_objs: dict[int: dict[int, rt.MaskObject]] = {}
        self.roarsegtracker = RoarSegTracker(self.segtracker_args, self.sam_args, self.aot_args)
        self.roarsegtracker.restart_tracker()
        #toggle use sam gap here
        self.use_sam_gap = False
        
    def get_segmentations(self, key_frame_idx=0):
        
        self.roarsegtracker.create_origin_mask(key_frame_idx)
        
        
        
    def set_tracker(self, annontation_dir=""):
        #TODO: set tracker values with anything it needs before segmentation tracking
        
        if annontation_dir != "":
            self.annotation_dir = annontation_dir
        self.roarsegtracker.start_seg_tracker_for_cvat(annotation_dir=annontation_dir)
        
    def store_tracker(self, frame=""):
        tracker_serial_data = RoarSegTracker.store_data(self.roarsegtracker)
        folder_name = "tracker_data"
        file_name = "tracker_data_frame_" + str(frame) + "_time_" + str(datetime.now())
        folder_path = os.path.join(self.output_dir, folder_name)
        file_path = os.path.join(folder_path, file_name)
        
        if not os.path.exists(folder_path):
                    os.makedirs(folder_path)
        with open(file_path, 'w') as outfile:
            outfile.write(tracker_serial_data)
    def get_tracker(self, frame="", time=""):
        folder_name = "tracker_data"
        file_name = "tracker_data_frame_" + str(frame) + "_time_" + time
        folder_path = os.path.join(self.output_dir, folder_name)
        file_path = os.path.join(folder_path, file_name)
        with open(file_path, 'r') as outfile:
            tracker_serial_data = outfile.read(outfile)
        self.roarsegtracker = RoarSegTracker.load_data(tracker_serial_data)
    def track(self):
        """
        Main function for tracking
        """
        start_frame = self.roarsegtracker.start_frame_idx
        end_frame = self.roarsegtracker.end_frame_idx
        #start at first annotated frame
        self.set_tracker(annontation_dir=self.annotation_dir)
        key_frame_queue = self.roarsegtracker.get_key_frame_arr()[:]
        next_key_frame = key_frame_queue.pop(0)
        curr_frame = self.roarsegtracker.get_key_frame_arr()[0]
        if curr_frame != next_key_frame:
            while curr_frame > next_key_frame:
                next_key_frame = key_frame_queue.pop(0)
            curr_frame = next_key_frame
        self.roarsegtracker.set_curr_key_frame(curr_frame)
                
        
        
        #cuda 
        torch.cuda.empty_cache()
        gc.collect()
        frames = list(range(curr_frame, end_frame+1))
        with torch.cuda.amp.autocast():
            while curr_frame in tqdm("Processing frames... ", frames):
                
                frame = rt.get_image(self.photo_dir, curr_frame)
                if curr_frame == next_key_frame:
                    #segment
                    #get new mask and tracking objects
                    pred_mask = self.get_segmentations(key_frame_idx=curr_frame)
                    self.roarsegtracker.set_curr_key_frame(next_key_frame)
                    #TODO: create mask object from pred_mask
                    self.track_key_frame_mask_objs[curr_frame] = \
                        self.roarsegtracker.get_key_frame_to_masks()[curr_frame]
                        
                    #TODO: add curr version of tracker to serialized save file in case of mem crash or seg fault
                    #cuda
                    torch.cuda.empty_cache()
                    gc.collect()
                    
                    self.roarsegtracker.add_reference_with_label(frame, pred_mask, )
                elif curr_frame % self.roarsegtracker.sam_gap == 0 and self.use_sam_gap:
                    #resegment on sam gap
                    pass
                else:
                    #TODO: create mask object from pred_mask
                    pred_mask = self.roarsegtracker.track(frame, update_memory=True)
                    
                    
                    self.track_key_frame_mask_objs[next_key_frame] = \
                        self.roarsegtracker.create_mask_objs_from_pred_mask(pred_mask)
                self.store_tracker(frame=str(curr_frame))
                #cuda
                torch.cuda.empty_cache()
                gc.collect()
                
    def save_annotations(self):
        folder_name = "annotations_output"
        folder_path = os.path.join(self.output_dir, folder_name)
        file_name = "annotations.xml"
        file_path = os.path.join(folder_path, file_name)
        rt.masks_to_xml(self.track_key_frame_mask_objs, file_path)
    def tune(self):
        #TODO: add tuning on first frame with gui to adjust tuning values for tracking
        
def main():
    sam_args['generator_args'] = {
        'points_per_side': 30,
        'pred_iou_thresh': 0.8,
        'stability_score_thresh': 0.9,
        'crop_n_layers': 1,
        'crop_n_points_downscale_factor': 2,
        'min_mask_region_area': 200,
    }
    
    segtracker_args = {
    'sam_gap': 7860, # the interval to run sam to segment new objects
    'min_area': 200, # minimal mask area to add a new mask as a new object
    'max_obj_num': 255, # maximal object number to track in a video
    'min_new_obj_iou': 0.8, # the area of a new object in the background should > 80% 
    }
    main_path = "/home/roar-nexus/Segment-and-Track-Anything/roar_annotations/23"
    photo_dir = os.path.join(main_path, "images")
    annotation_path = os.path.join(main_path, "annotations.xml")
    output_dir = os.path.join(main_path, "output")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    main_hub = MainHub(segtracker_args=segtracker_args, sam_args=sam_args, aot_args=aot_args, 
                       photo_dir=photo_dir, annotation_dir=annotation_path,
                       output_dir=output_dir)
    
    #start tracking
    main_hub.track()   
    
    #save annotations
    main_hub.save_annotations()
    
    print("Done!") 
    
if __name__ == "__main__":
    main()
                
        
                    
    
                