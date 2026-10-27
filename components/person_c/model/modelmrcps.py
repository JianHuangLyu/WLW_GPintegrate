import torch
import copy
import segmentation_models_pytorch.utils as smputils

from .modelbase import BaseModel
import numpy as np

class MRCPSModel(BaseModel):
    def __init__(self, traincfg):
        super().__init__(traincfg)

        self.unflatten_json(self.traincfg['branch1'])
        self.branch1 = self._initmodel(self.traincfg['branch1'])

        self.unflatten_json(self.traincfg['branch2'])
        self.branch2 = self._initmodel(self.traincfg['branch2'])


        # self.server_model = None  #-----vote

    def forward(self, x, lrx, step=1):
        # in lightning, forward defines the prediction/inference actions
        """
        Args:
            x       input tensor
            step    predict branch
        """
        if step == 0:
            return torch.argmax(
                self.branch1(x, lrx).softmax(1) + self.branch2(x, lrx).softmax(1)
                , dim=1)
        elif step == 3:
            p1 = self.branch1(x, lrx).softmax(1)
            p2 = self.branch2(x, lrx).softmax(1)
            return torch.argmax(p1+p2, dim=1), torch.argmax(p1, dim=1), torch.argmax(p2, dim=1)
        else:
            return torch.argmax(getattr(self, f'branch{step}')(x, lrx), dim=1)

    # def evaRecords_init(self):
    #     self.evaRecords = []
    #     self.b_counts = []

    # def evaRecords_append(self, records):
    #     self.evaRecords.append(records)

    # def evaRecords_load(self):
    #     mean_batch = np.array(self.evaRecords).astype('float64')
    #     b_counts = np.array(self.b_counts).astype('float64')
    #     for i in range(len(b_counts)):
    #         mean_batch[i]/=b_counts[i]
    #     return mean_batch
        #return self.evaRecords

    def training_step(self, batch, batch_idx):
        # image, mask, lrimage, lrmask = batch["label"]
        # lrmask = self._downpool(lrmask)

        predmask = []
        opt1, opt2 = self.optimizers()

        # supervised
        if "label" in batch:
            image, mask, lrimage, lrnmask = batch["label"]
            
            if len(image)>0:
                y_pred_1_sup = self.branch1(image, lrimage)
                y_pred_2_sup = self.branch2(image, lrimage)
                
                sup_loss_1 = self.criterion(y_pred_1_sup, mask)
                sup_loss_2 = self.criterion(y_pred_2_sup, mask)
                self.log(f"train 1 sup loss", sup_loss_1)
                self.log(f"train 2 sup loss", sup_loss_2)
                totalloss = sup_loss_1 + sup_loss_2

                predmask.append(torch.argmax(y_pred_1_sup, dim=1))
                predmask.append(torch.argmax(y_pred_2_sup, dim=1))

        if "unlabel" in batch:
            image_un, lrimage_un = batch["unlabel"]
            
            with torch.no_grad():
                y_pred_un_1 = self.branch1(image_un, lrimage_un)
                y_pred_un_2 = self.branch2(image_un, lrimage_un)
                pseudomask_un_1 = torch.argmax(y_pred_un_1, dim=1)
                pseudomask_un_2 = torch.argmax(y_pred_un_2, dim=1)
            cps_loss_1 = self.criterion(y_pred_un_1, pseudomask_un_2) * self.consistencyratio
            cps_loss_2 = self.criterion(y_pred_un_2, pseudomask_un_1) * self.consistencyratio
            
            self.log(f"train 1 cps loss", cps_loss_1)
            self.log(f"train 2 cps loss", cps_loss_2)
            totalloss += (cps_loss_1 + cps_loss_2)

        self.log(f"train loss", totalloss.item() / 2, prog_bar=True)
        
        self._evaluate(predmask, mask, "train")

        # backwarding
        totalloss /= self.accumulate_grad_batches
        self.manual_backward(totalloss)
        if (batch_idx + 1) % self.accumulate_grad_batches == 0:
            opt1.step()
            opt2.step()
            opt1.zero_grad()
            opt2.zero_grad()
        
        if (batch_idx + 1) % self.accumulate_grad_batches == 0:
            self._training_sch_on_step()

    def validation_step(self, batch, batch_idx):
        # return
        image, mask, lrimage = batch
        predmask = []
        y_pred_1 = self.branch1(image, lrimage)
        predmask.append(torch.argmax(y_pred_1, dim=1))
        y_pred_2 = self.branch2(image, lrimage)
        predmask.append(torch.argmax(y_pred_2, dim=1))

        loss_1 = self.criterion(y_pred_1, mask)
        self.log(f"valid 1 loss", loss_1)
        loss_2 = self.criterion(y_pred_2, mask)
        self.log(f"valid 2 loss", loss_2)

        self.log(f"valid loss", (loss_1 + loss_2) / 2, prog_bar=True)

        self._evaluate(predmask, mask, "valid")

        predensem_b1 = []
        predensem_b2 = []
        predensem = []
        predensem_b1.append(torch.argmax(y_pred_1.softmax(1), dim=1))
        predensem_b2.append(torch.argmax(y_pred_2.softmax(1), dim=1))
        voting = y_pred_1.softmax(1) + y_pred_2.softmax(1)
        predensem.append(torch.argmax(voting, dim=1))
        # print('????shape', len(predensem))
        #torch.argmax(self.branch1(x, lrx).softmax(1) + self.branch2(x, lrx).softmax(1), dim=1)
        eva_result_b1 = self._evaluate(predensem_b1, mask, "valid ens")
        eva_result_b2 = self._evaluate(predensem_b2, mask, "valid ens")
        eva_result = self._evaluate(predensem, mask, "valid ens")

        eva_criteria_arr = np.array([eva_result_b1, eva_result_b2, eva_result])
        if batch_idx==0:
            self.evaRecords.append(eva_criteria_arr)
            self.b_counts.append(1)
        else:
            self.evaRecords[-1]+=eva_criteria_arr
            self.b_counts[-1]+=1
        # print('>>>>', (np.array(self.evaRecords)).shape)
        # print('>>>>',self.b_counts)

    def test_step(self, batch, batch_idx):
        # return
        image, mask, lrimage = batch
        predmask = []
        y_pred_1 = self.branch1(image, lrimage)
        predmask.append(torch.argmax(y_pred_1, dim=1))
        y_pred_2 = self.branch2(image, lrimage)
        predmask.append(torch.argmax(y_pred_2, dim=1))
        
        self._evaluate(predmask, mask, "test")

        predensem = []
        voting = y_pred_1.softmax(1) + y_pred_2.softmax(1)
        predensem.append(torch.argmax(voting, dim=1))

        self._evaluate(predensem, mask, "test ens")
    '''
    def configure_optimizers(self):
        opts = []
        schs = []

        optimizer1 = self._initoptimizer(self.branch1.parameters())
        scheduler1 = self._initscheduler(optimizer1)
        opts.append(optimizer1)
        schs.append(scheduler1)

        optimizer2 = self._initoptimizer(self.branch2.parameters())
        scheduler2 = self._initscheduler(optimizer2)
        opts.append(optimizer2)
        schs.append(scheduler2)

        return opts, schs
    '''
    '''
    def _initmetrics(self):
        return [
            smputils.metrics.IoU(),
        ]
    '''
