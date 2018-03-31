import time

import torch.nn.functional as F
from torch.optim.lr_scheduler import ReduceLROnPlateau

from trainers.trainer import Trainer
from utils.serialization import save_checkpoint


class SICKTrainer(Trainer):

    def train_epoch(self, epoch):
        self.model.train()
        total_loss = 0
        for batch_idx, batch in enumerate(self.train_loader):
            self.optimizer.zero_grad()

            # Select embedding
            sent1, sent2, sent1_nonstatic, sent2_nonstatic = self.get_sentence_embeddings(batch)

            output = self.model(sent1, sent2, batch.ext_feats, batch.dataset.word_to_doc_cnt, batch.sentence_1_raw, batch.sentence_2_raw, sent1_nonstatic, sent2_nonstatic)
            loss = F.kl_div(output, batch.label)
            total_loss += loss.data[0]
            loss.backward()
            self.optimizer.step()
            if batch_idx % self.log_interval == 0:
                self.logger.info('Train Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.6f}'.format(
                    epoch, min(batch_idx * self.batch_size, len(batch.dataset.examples)),
                    len(batch.dataset.examples),
                    100. * batch_idx / (len(self.train_loader)), loss.data[0])
                )

        if self.use_tensorboard:
            self.writer.add_scalar('sick/train/kl_div_loss', total_loss, epoch)

        return total_loss

    def train(self, epochs):
        scheduler = ReduceLROnPlateau(self.optimizer, mode='max', factor=self.lr_reduce_factor, patience=self.patience)
        epoch_times = []
        prev_loss = -1
        best_dev_score = -1
        for epoch in range(1, epochs + 1):
            start = time.time()
            self.logger.info('Epoch {} started...'.format(epoch))
            self.train_epoch(epoch)

            dev_scores = self.evaluate(self.dev_evaluator, 'dev')
            new_loss = dev_scores[2]

            if self.use_tensorboard:
                self.writer.add_scalar('sick/lr', self.optimizer.param_groups[0]['lr'], epoch)
                self.writer.add_scalar('sick/dev/pearson_r', dev_scores[0], epoch)
                self.writer.add_scalar('sick/dev/kl_div_loss', new_loss, epoch)

            end = time.time()
            duration = end - start
            self.logger.info('Epoch {} finished in {:.2f} minutes'.format(epoch, duration / 60))
            epoch_times.append(duration)

            if dev_scores[0] > best_dev_score:
                best_dev_score = dev_scores[0]
                save_checkpoint(epoch, self.model.arch, self.model.state_dict(), self.optimizer.state_dict(), best_dev_score, self.model_outfile)

            if abs(prev_loss - new_loss) <= 0.0002:
                self.logger.info('Early stopping. Loss changed by less than 0.0002.')
                break

            prev_loss = new_loss
            scheduler.step(dev_scores[0])

        self.logger.info('Training took {:.2f} minutes overall...'.format(sum(epoch_times) / 60))
