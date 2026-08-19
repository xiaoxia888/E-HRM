pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

ApplicationWindow {
    id: window
    required property var backend
    width: 1480
    height: 900
    minimumWidth: 1180
    minimumHeight: 720
    visible: true
    title: "信息化人力工作台"
    color: "#f5f7fa"
    font.family: Qt.platform.os === "windows" ? "Microsoft YaHei UI" : "PingFang SC"

    property int activeModule: 0

    onClosing: function(close) {
        if (window.backend.running) {
            close.accepted = false
            runningCloseDialog.open()
        } else if (!window.backend.shutdown()) {
            close.accepted = false
            messageDialog.heading = "正在关闭浏览器"
            messageDialog.message = "自动化工作线程尚未完全退出，请稍后再关闭工作台。"
            messageDialog.open()
        }
    }

    FileDialog {
        id: importDialog
        title: "导入人员 Excel"
        currentFolder: window.backend.downloadsFolderUrl
        nameFilters: ["Excel 工作簿 (*.xlsx *.xlsm)"]
        fileMode: FileDialog.OpenFile
        onAccepted: window.backend.importExcel(selectedFile)
    }

    FileDialog {
        id: templateDialog
        title: "保存 Excel 模板"
        currentFolder: window.backend.downloadsFolderUrl
        nameFilters: ["Excel 工作簿 (*.xlsx)"]
        fileMode: FileDialog.SaveFile
        onAccepted: window.backend.saveTemplate(selectedFile)
    }

    FolderDialog {
        id: outputDialog
        title: "选择保存位置"
        currentFolder: window.backend.downloadsFolderUrl
        onAccepted: window.backend.setOutputFolder(selectedFolder)
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.preferredWidth: 220
            Layout.fillHeight: true
            color: "#ffffff"
            border.color: "#e5e8ee"

            Column {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 7

                Item {
                    width: parent.width
                    height: 82
                    Row {
                        anchors.left: parent.left
                        anchors.leftMargin: 9
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 13
                        Rectangle {
                            width: 44
                            height: 44
                            radius: 9
                            color: "#1677ff"
                            Image {
                                anchors.centerIn: parent
                                width: 27
                                height: 27
                                source: "../assets/app.svg"
                            }
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "信息化人力"
                            color: "#1e2430"
                            font.pixelSize: 20
                            font.weight: Font.Bold
                        }
                    }
                }

                NavItem {
                    width: parent.width
                    text: "权益单获取"
                    iconSource: "../assets/document.svg"
                    selected: window.activeModule === 0
                    onClicked: window.activeModule = 0
                }
                NavItem {
                    width: parent.width
                    text: "上传至 ERP"
                    iconSource: "../assets/upload.svg"
                    reserved: true
                    selected: window.activeModule === 1
                    onClicked: window.activeModule = 1
                }
                NavItem {
                    width: parent.width
                    text: "任务记录"
                    iconSource: "../assets/history.svg"
                    selected: window.activeModule === 2
                    onClicked: window.activeModule = 2
                }

                Item { width: 1; height: Math.max(10, parent.height - 82 - 52 * 4 - 28) }

                NavItem {
                    width: parent.width
                    text: "系统设置"
                    iconSource: "../assets/settings.svg"
                    selected: window.activeModule === 3
                    onClicked: window.activeModule = 3
                }
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: window.activeModule

            Item {
                id: rightsPage

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 105
                        color: "#ffffff"
                        border.color: "#e5e8ee"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 32
                            anchors.rightMargin: 28
                            Column {
                                Layout.fillWidth: true
                                spacing: 6
                                Text {
                                    text: "单位权益单获取"
                                    color: "#1d2433"
                                    font.pixelSize: 25
                                    font.weight: Font.Bold
                                }
                                Text {
                                    text: "导入人员信息，自动查询并下载单位权益单"
                                    color: "#6b7380"
                                    font.pixelSize: 14
                                }
                            }
                            AppButton {
                                text: "下载 Excel 模板"
                                iconSource: "../assets/download.svg"
                                onClicked: templateDialog.open()
                            }
                            AppButton {
                                text: "导入 Excel"
                                iconSource: "../assets/upload.svg"
                                outline: true
                                onClicked: importDialog.open()
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.margins: 24
                        Layout.topMargin: 20
                        spacing: 18

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            radius: 10
                            color: "#ffffff"
                            border.color: "#e1e5eb"

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 20
                                spacing: 15

                                Row {
                                    Layout.fillWidth: true
                                    spacing: 8
                                    Image {
                                        width: 22
                                        height: 22
                                        source: "../assets/document.svg"
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: window.backend.fileSummary
                                        color: "#242a36"
                                        font.pixelSize: 16
                                        font.weight: Font.DemiBold
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        visible: window.backend.imported
                                        text: "· 校验通过"
                                        color: "#12a150"
                                        font.pixelSize: 15
                                        font.weight: Font.DemiBold
                                    }
                                }

                                Row {
                                    Layout.fillWidth: true
                                    spacing: 12
                                    MetricCard {
                                        width: 205
                                        title: "人员"
                                        value: window.backend.peopleCount.toString()
                                        iconSource: "../assets/people.svg"
                                    }
                                    MetricCard {
                                        width: 205
                                        title: "查询条件"
                                        value: window.backend.conditionCount + " 组"
                                        iconSource: "../assets/list.svg"
                                    }
                                    MetricCard {
                                        width: 205
                                        title: "预计 PDF"
                                        value: window.backend.expectedPdfCount + " 份"
                                        iconSource: "../assets/document.svg"
                                    }
                                }

                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: warningText.implicitHeight + 24
                                    radius: 7
                                    color: "#fff8e8"
                                    border.color: "#ffc866"
                                    Row {
                                        anchors.fill: parent
                                        anchors.margins: 12
                                        spacing: 10
                                        Rectangle {
                                            width: 19
                                            height: 19
                                            radius: 10
                                            color: "transparent"
                                            border.color: "#b87503"
                                            Text {
                                                anchors.centerIn: parent
                                                text: "i"
                                                color: "#b87503"
                                                font.pixelSize: 12
                                                font.weight: Font.Bold
                                            }
                                        }
                                        Text {
                                            id: warningText
                                            width: parent.width - 34
                                            anchors.verticalCenter: parent.verticalCenter
                                            text: window.backend.planMessage
                                            color: "#9a6200"
                                            font.pixelSize: 14
                                            wrapMode: Text.WordWrap
                                        }
                                    }
                                }

                                Text {
                                    text: "导入数据预览"
                                    color: "#202632"
                                    font.pixelSize: 18
                                    font.weight: Font.Bold
                                }

                                Rectangle {
                                    id: tablePanel
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    radius: 7
                                    color: "#ffffff"
                                    border.color: "#e3e7ed"
                                    clip: true

                                    property var ratios: [0.07, 0.16, 0.14, 0.10, 0.20, 0.09, 0.12, 0.12]
                                    property var headers: ["状态", "单位", "部门", "姓名", "身份证", "险种", "开始时间", "结束时间"]

                                    Column {
                                        anchors.fill: parent

                                        Rectangle {
                                            width: parent.width
                                            height: 48
                                            color: "#f7f8fa"
                                            Row {
                                                anchors.fill: parent
                                                Repeater {
                                                    model: tablePanel.headers
                                                    Rectangle {
                                                        id: headerCell
                                                        required property int index
                                                        required property string modelData
                                                        width: tablePanel.width * tablePanel.ratios[headerCell.index]
                                                        height: 48
                                                        color: "transparent"
                                                        border.color: "#ebedf1"
                                                        Text {
                                                            anchors.centerIn: parent
                                                            text: headerCell.modelData
                                                            color: "#566071"
                                                            font.pixelSize: 13
                                                            font.weight: Font.DemiBold
                                                        }
                                                    }
                                                }
                                            }
                                        }

                                        ListView {
                                            id: recordList
                                            width: parent.width
                                            height: parent.height - 48
                                            clip: true
                                            model: window.backend.records
                                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                                            delegate: Rectangle {
                                                id: recordRow
                                                required property int index
                                                required property var modelData
                                                width: recordList.width
                                                height: 50
                                                color: recordRow.index % 2 ? "#fbfcfd" : "#ffffff"
                                                border.color: "#edf0f3"
                                                Row {
                                                    anchors.fill: parent
                                                    Repeater {
                                                        model: [
                                                            recordRow.modelData.status, recordRow.modelData.unit,
                                                            recordRow.modelData.department, recordRow.modelData.name,
                                                            recordRow.modelData.identity, recordRow.modelData.insurance,
                                                            recordRow.modelData.startMonth, recordRow.modelData.endMonth
                                                        ]
                                                        Item {
                                                            id: dataCell
                                                            required property int index
                                                            required property string modelData
                                                            width: tablePanel.width * tablePanel.ratios[dataCell.index]
                                                            height: 50
                                                            Text {
                                                                anchors.fill: parent
                                                                anchors.leftMargin: dataCell.index === 0 ? 0 : 10
                                                                anchors.rightMargin: 8
                                                                verticalAlignment: Text.AlignVCenter
                                                                horizontalAlignment: dataCell.index === 0 || dataCell.index >= 5 ? Text.AlignHCenter : Text.AlignLeft
                                                                text: dataCell.modelData
                                                                color: dataCell.index === 0 ? "#12a150" : "#303744"
                                                                font.pixelSize: 13
                                                                font.weight: dataCell.index === 0 ? Font.DemiBold : Font.Normal
                                                                elide: Text.ElideRight
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 7
                                    Text {
                                        text: window.backend.statusText
                                        color: "#687181"
                                        font.pixelSize: 13
                                    }
                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: window.backend.running ? 7 : 0
                                        visible: window.backend.running
                                        radius: 4
                                        color: "#e7edf4"
                                        Rectangle {
                                            height: parent.height
                                            width: parent.width * Math.min(1, window.backend.progressCurrent / Math.max(1, window.backend.progressTotal))
                                            radius: 4
                                            color: "#1677ff"
                                            Behavior on width { NumberAnimation { duration: 220 } }
                                        }
                                    }
                                }
                            }
                        }

                        Rectangle {
                            Layout.preferredWidth: 360
                            Layout.fillHeight: true
                            radius: 10
                            color: "#ffffff"
                            border.color: "#e1e5eb"

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 20
                                spacing: 14

                                Text {
                                    text: "导出设置"
                                    color: "#202632"
                                    font.pixelSize: 19
                                    font.weight: Font.Bold
                                }

                                ModeCard {
                                    Layout.fillWidth: true
                                    title: "相同查询条件合并"
                                    helper: "预计生成 " + window.backend.batchExpectedPdfCount + " 份 PDF"
                                    selected: window.backend.exportMode === "batch"
                                    onClicked: window.backend.setExportMode("batch")
                                }
                                ModeCard {
                                    Layout.fillWidth: true
                                    title: "每人单独一份"
                                    helper: "预计生成 " + window.backend.peopleCount + " 份 PDF"
                                    selected: window.backend.exportMode === "individual"
                                    onClicked: window.backend.setExportMode("individual")
                                }

                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 116
                                    radius: 8
                                    color: "#ffffff"
                                    border.color: "#e1e5eb"
                                    Column {
                                        anchors.fill: parent
                                        anchors.margins: 15
                                        spacing: 11
                                        Text {
                                            text: "高级设置"
                                            color: "#29303d"
                                            font.pixelSize: 15
                                            font.weight: Font.DemiBold
                                        }
                                        RowLayout {
                                            width: parent.width
                                            Text {
                                                Layout.fillWidth: true
                                                text: "单批最多人数"
                                                color: "#303744"
                                                font.pixelSize: 14
                                            }
                                            BatchSizeControl {
                                                from: 1
                                                to: 100
                                                value: window.backend.batchSize
                                                enabled: window.backend.exportMode === "batch"
                                                onValueEdited: function(value) {
                                                    window.backend.setBatchSize(value)
                                                }
                                            }
                                        }
                                        Text {
                                            text: "每份 PDF 最多包含 1–100 人"
                                            color: "#8a93a2"
                                            font.pixelSize: 12
                                        }
                                    }
                                }

                                Text {
                                    text: "保存位置"
                                    color: "#303744"
                                    font.pixelSize: 14
                                    font.weight: Font.Medium
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 42
                                        radius: 7
                                        color: "#ffffff"
                                        border.color: "#d9dde5"
                                        Text {
                                            anchors.fill: parent
                                            anchors.leftMargin: 12
                                            anchors.rightMargin: 12
                                            verticalAlignment: Text.AlignVCenter
                                            text: window.backend.outputPath
                                            color: "#394150"
                                            font.pixelSize: 13
                                            elide: Text.ElideMiddle
                                        }
                                    }
                                    AppButton {
                                        text: "更改"
                                        onClicked: outputDialog.open()
                                    }
                                }

                                Row {
                                    spacing: 9
                                    opacity: 0.5
                                    Rectangle {
                                        width: 17
                                        height: 17
                                        radius: 3
                                        color: "#f1f3f5"
                                        border.color: "#cfd4dc"
                                    }
                                    Text {
                                        text: "下载完成后进入 ERP 上传"
                                        color: "#566071"
                                        font.pixelSize: 14
                                    }
                                }
                                Text {
                                    text: "ERP 上传功能接入后启用"
                                    color: "#8b93a1"
                                    font.pixelSize: 13
                                }

                                Item { Layout.fillHeight: true }

                                AppButton {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 54
                                    text: !window.backend.running
                                        ? "获取权益单"
                                        : window.backend.stopping
                                            ? "正在安全停止…"
                                            : "停止任务"
                                    primary: !window.backend.running
                                    danger: window.backend.running
                                    enabled: window.backend.imported && !window.backend.stopping
                                    onClicked: {
                                        if (window.backend.running)
                                            stopTaskDialog.open()
                                        else
                                            window.backend.prepareExecution()
                                    }
                                }
                            }
                        }
                    }
                }
            }

            PlaceholderPage {
                title: "上传至 ERP"
                subtitle: "权益单下载完成后，可在这里选择任务结果并自动上传至 ERP。"
                description: "该模块已预留，后续接入 ERP 登录、文件匹配、上传及结果回写流程。"
            }
            PlaceholderPage {
                title: "任务记录"
                subtitle: "统一查看权益单下载和 ERP 上传任务。"
                description: "后续将支持按人员、时间和状态筛选，并可仅重试失败项目。"
            }
            PlaceholderPage {
                title: "系统设置"
                subtitle: "管理默认保存目录、浏览器和批量处理参数。"
                description: "当前批量人数可直接在权益单获取页的高级设置中调整。"
            }
        }
    }

    Dialog {
        id: confirmationDialog
        width: 600
        height: Math.min(690, confirmationColumn.implicitHeight + 48)
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        modal: true
        focus: true
        padding: 24
        closePolicy: Popup.CloseOnEscape
        background: Rectangle {
            color: "#ffffff"
            radius: 11
            border.color: "#dfe3e8"
        }
        contentItem: Column {
            id: confirmationColumn
            spacing: 17
            Text {
                text: "确认执行"
                color: "#202632"
                font.pixelSize: 22
                font.weight: Font.Bold
            }
            Text {
                width: parent.width
                text: "共 <b><font color='#1677ff'>" + window.backend.peopleCount + "</font></b> 人，将按 "
                      + "<b><font color='#1677ff'>" + window.backend.conditionCount + "</font></b> 组查询条件生成 "
                      + "<b><font color='#1677ff'>" + window.backend.expectedPdfCount + "</font></b> 份 PDF"
                textFormat: Text.RichText
                color: "#303744"
                font.pixelSize: 17
            }
            Rectangle {
                width: parent.width
                height: Math.min(225, Math.max(58, window.backend.conditionSummaries.length * 52 + 12))
                radius: 7
                color: "#ffffff"
                border.color: "#dfe3e8"
                ListView {
                    anchors.fill: parent
                    anchors.margins: 6
                    clip: true
                    model: window.backend.conditionSummaries
                    delegate: Rectangle {
                        id: conditionRow
                        required property var modelData
                        width: ListView.view.width
                        height: 52
                        color: "transparent"
                        border.color: "#edf0f3"
                        Text {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 8
                            verticalAlignment: Text.AlignVCenter
                            text: conditionRow.modelData.unit + " · " + conditionRow.modelData.insurance + " · "
                                  + conditionRow.modelData.startMonth + " 至 " + conditionRow.modelData.endMonth + " · "
                                  + conditionRow.modelData.peopleCount + " 人"
                                  + (conditionRow.modelData.pdfCount > 1 ? " · " + conditionRow.modelData.pdfCount + " 份 PDF" : "")
                            color: "#303744"
                            font.pixelSize: 14
                            elide: Text.ElideRight
                        }
                    }
                }
            }
            Rectangle {
                width: parent.width
                height: 68
                radius: 7
                color: "#f0f7ff"
                border.color: "#91caff"
                Text {
                    anchors.fill: parent
                    anchors.margins: 12
                    text: "执行后将打开浏览器，请完成登录和安全验证。\n程序会在当前浏览器中自动继续。"
                    color: "#245b9e"
                    font.pixelSize: 14
                    lineHeight: 1.35
                }
            }
            Text {
                text: "结果 Excel <b><font color='#1677ff'>1</font></b> 份 · PDF "
                      + "<b><font color='#1677ff'>" + window.backend.expectedPdfCount + "</font></b> 份"
                textFormat: Text.RichText
                color: "#303744"
                font.pixelSize: 16
            }
            Text {
                width: parent.width
                text: "保存至：" + window.backend.confirmationOutputPath
                color: "#717a89"
                font.pixelSize: 13
                wrapMode: Text.WrapAnywhere
            }
            Row {
                anchors.right: parent.right
                spacing: 10
                AppButton {
                    text: "返回修改"
                    onClicked: confirmationDialog.close()
                }
                AppButton {
                    text: "确认并开始"
                    primary: true
                    onClicked: {
                        confirmationDialog.close()
                        window.backend.executePrepared()
                    }
                }
            }
        }
    }

    Dialog {
        id: validationDialog
        property string summary: ""
        property string details: ""
        width: 580
        height: details.length > 0 ? 430 : 250
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        modal: true
        padding: 24
        background: Rectangle { color: "#ffffff"; radius: 11; border.color: "#dfe3e8" }
        contentItem: ColumnLayout {
            spacing: 15
            Text {
                text: "Excel 数据校验失败"
                color: "#202632"
                font.pixelSize: 21
                font.weight: Font.Bold
            }
            Text {
                Layout.fillWidth: true
                text: validationDialog.summary
                color: "#303744"
                font.pixelSize: 15
                wrapMode: Text.WordWrap
            }
            Text {
                visible: validationDialog.details.length > 0
                text: "请修改以下内容后重新导入："
                color: "#737c8b"
                font.pixelSize: 13
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: validationDialog.details.length > 0
                radius: 7
                color: "#f7f8fa"
                border.color: "#dfe3e8"
                ScrollView {
                    anchors.fill: parent
                    anchors.margins: 12
                    TextArea {
                        text: validationDialog.details
                        readOnly: true
                        wrapMode: TextArea.Wrap
                        color: "#303744"
                        background: null
                    }
                }
            }
            Row {
                Layout.alignment: Qt.AlignRight
                AppButton { text: "我知道了"; primary: true; onClicked: validationDialog.close() }
            }
        }
    }

    Dialog {
        id: messageDialog
        property string heading: ""
        property string message: ""
        width: 520
        height: 260
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        modal: true
        padding: 24
        background: Rectangle { color: "#ffffff"; radius: 11; border.color: "#dfe3e8" }
        contentItem: ColumnLayout {
            spacing: 16
            Text { text: messageDialog.heading; font.pixelSize: 21; font.weight: Font.Bold; color: "#202632" }
            Text { Layout.fillWidth: true; Layout.fillHeight: true; text: messageDialog.message; wrapMode: Text.WrapAnywhere; color: "#4d5665"; font.pixelSize: 14 }
            Row { Layout.alignment: Qt.AlignRight; AppButton { text: "确定"; primary: true; onClicked: messageDialog.close() } }
        }
    }

    Dialog {
        id: resultDialog
        property string heading: ""
        property string message: ""
        property string details: ""
        width: 600
        height: 340
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        modal: true
        padding: 24
        background: Rectangle { color: "#ffffff"; radius: 11; border.color: "#dfe3e8" }
        contentItem: ColumnLayout {
            spacing: 15
            Text { text: resultDialog.heading; font.pixelSize: 21; font.weight: Font.Bold; color: "#202632" }
            Text { text: resultDialog.message; font.pixelSize: 16; color: "#303744" }
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 7
                color: "#f7f8fa"
                border.color: "#e1e5eb"
                Text { anchors.fill: parent; anchors.margins: 13; text: resultDialog.details; wrapMode: Text.WrapAnywhere; color: "#626c7b"; font.pixelSize: 13 }
            }
            Row {
                Layout.alignment: Qt.AlignRight
                spacing: 10
                AppButton { text: "关闭"; onClicked: resultDialog.close() }
                AppButton { text: "打开结果文件夹"; primary: true; onClicked: window.backend.openFolder(window.backend.lastOutputPath) }
            }
        }
    }

    Dialog {
        id: stopTaskDialog
        width: 500
        height: 285
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        modal: true
        padding: 24
        closePolicy: Popup.CloseOnEscape
        background: Rectangle { color: "#ffffff"; radius: 11; border.color: "#dfe3e8" }
        contentItem: ColumnLayout {
            spacing: 16
            Text {
                text: "确认停止当前任务？"
                color: "#202632"
                font.pixelSize: 21
                font.weight: Font.Bold
            }
            Text {
                Layout.fillWidth: true
                Layout.fillHeight: true
                text: "程序会在最近的安全节点停止。\n\n已下载的 PDF 会保留；尚未处理的人员将在结果 Excel 中标记为“用户提前停止任务”。"
                wrapMode: Text.WordWrap
                color: "#4d5665"
                font.pixelSize: 14
                lineHeight: 1.3
            }
            Row {
                Layout.alignment: Qt.AlignRight
                spacing: 10
                AppButton { text: "继续执行"; onClicked: stopTaskDialog.close() }
                AppButton {
                    text: "确认停止"
                    danger: true
                    onClicked: {
                        stopTaskDialog.close()
                        window.backend.requestStop()
                    }
                }
            }
        }
    }

    Dialog {
        id: runningCloseDialog
        width: 470
        height: 220
        x: Math.round((window.width - width) / 2)
        y: Math.round((window.height - height) / 2)
        modal: true
        padding: 24
        background: Rectangle { color: "#ffffff"; radius: 11; border.color: "#dfe3e8" }
        contentItem: ColumnLayout {
            spacing: 16
            Text { text: "任务正在执行"; font.pixelSize: 21; font.weight: Font.Bold; color: "#202632" }
            Text {
                Layout.fillWidth: true
                Layout.fillHeight: true
                text: "请等待当前任务完成，或先安全停止任务后再退出。"
                color: "#4d5665"
                font.pixelSize: 14
                wrapMode: Text.WordWrap
            }
            Row {
                Layout.alignment: Qt.AlignRight
                spacing: 10
                AppButton { text: "继续执行"; onClicked: runningCloseDialog.close() }
                AppButton {
                    text: "停止任务"
                    danger: true
                    enabled: !window.backend.stopping
                    onClicked: {
                        runningCloseDialog.close()
                        stopTaskDialog.open()
                    }
                }
            }
        }
    }

    Connections {
        target: window.backend
        function onValidationFailed(summary, details) {
            validationDialog.summary = summary
            validationDialog.details = details
            validationDialog.open()
        }
        function onNotification(title, message) {
            messageDialog.heading = title
            messageDialog.message = message
            messageDialog.open()
        }
        function onConfirmationReady() {
            confirmationDialog.open()
        }
        function onExecutionFinished(title, message, details) {
            resultDialog.heading = title
            resultDialog.message = message
            resultDialog.details = details
            resultDialog.open()
        }
    }
}
